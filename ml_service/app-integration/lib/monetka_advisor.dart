// Советник — on-device inference for the «Монетка» Flutter app.
//
// This is the contract the app implements, kept in the platform repository next
// to the exporter so the two cannot drift apart unnoticed.
//
// Everything here runs offline: nothing leaves the device. That is not a
// nice-to-have — ТЗ §3.1.5 requires the main game loop to work without a
// network, and §3.5 forbids sending a child's data anywhere.
//
// pubspec.yaml:
//   dependencies:
//     onnxruntime: ^1.4.1
//
//   flutter:
//     assets:
//       - assets/models/behaviour_segment.onnx
//       - assets/models/behaviour_segment.json
//
// The two asset files are produced by `monetka export` in the platform repo.

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;
import 'package:onnxruntime/onnxruntime.dart';

// ---------------------------------------------------------------------------
// Model metadata
// ---------------------------------------------------------------------------

/// Metadata written beside the model by the exporter.
class ModelCard {
  const ModelCard({
    required this.name,
    required this.version,
    required this.featureNames,
    required this.classNames,
    this.maxPeriodNo,
    this.abstainOutsideRange = true,
  });

  final String name;
  final String version;

  /// Order matters. ONNX takes an unnamed tensor, so a vector assembled in a
  /// different order still returns a confident answer — just a meaningless one.
  final List<String> featureNames;
  final List<String> classNames;

  /// Last period in which the model has measured skill. Past it the model
  /// abstains: behaviour archetypes converge as a child learns, and a
  /// prediction nobody validated is worse than no prediction.
  final int? maxPeriodNo;
  final bool abstainOutsideRange;

  factory ModelCard.fromJson(Map<String, dynamic> json) {
    final applicability =
        (json['applicability'] as Map<String, dynamic>?) ?? const {};
    return ModelCard(
      name: json['name'] as String,
      version: json['version'] as String,
      featureNames: (json['feature_names'] as List).cast<String>(),
      classNames: ((json['class_names'] as List?) ?? const []).cast<String>(),
      maxPeriodNo: applicability['max_period_no'] as int?,
      abstainOutsideRange:
          (applicability['abstain_outside_range'] as bool?) ?? true,
    );
  }
}

// ---------------------------------------------------------------------------
// Domain
// ---------------------------------------------------------------------------

/// Behaviour pattern of one closed game period.
enum Segment { planner, spender, saver, explorer, unknown }

/// What the Советник shows. Always a consequence plus a next step — ТЗ §2.5.9
/// requires feedback to explain what happened *and* offer a way forward.
class Hint {
  const Hint(this.id, this.text, this.nextStep, this.source);

  final String id;
  final String text;
  final String nextStep;

  /// `rule` or `model`. Worth surfacing in debug builds: a hint that silently
  /// came from a model is how you lose track of what the product is doing.
  final String source;
}

/// The minimum the advisor needs. Deliberately free of identifiers: no game
/// name, no pet name, no device id (ТЗ §3.5).
class PeriodSnapshot {
  const PeriodSnapshot({
    required this.essentialCoverage,
    required this.planAdherence,
    required this.savingsRate,
    required this.periodsCompleted,
    this.optionalSpendShare = 0.0,
    this.rejectedPurchases = 0,
    this.withdrawals = 0,
    this.revisionsCount = 0,
    this.purchasesEssential = 0,
    this.purchasesOptional = 0,
    this.questsCompleted = 0,
    this.questOutcomeScore = 0.0,
    this.avgEssentialCoverage,
    this.avgPlanAdherence,
    this.avgSavingsRate,
    this.avgOptionalShare,
    this.planAdherenceVolatility = 0.0,
    this.savingsRegularity = 0.0,
    this.planAdherenceDelta = 0.0,
    this.unallocatedShare = 0.0,
  });

  final double essentialCoverage;
  final double planAdherence;
  final double savingsRate;
  final int periodsCompleted;
  final double optionalSpendShare;
  final int rejectedPurchases;
  final int withdrawals;
  final int revisionsCount;
  final int purchasesEssential;
  final int purchasesOptional;
  final int questsCompleted;
  final double questOutcomeScore;

  /// Rolling means over the last three periods. The app keeps these locally;
  /// when they are absent the current period stands in, which is the same
  /// convention the reference implementation uses.
  final double? avgEssentialCoverage;
  final double? avgPlanAdherence;
  final double? avgSavingsRate;
  final double? avgOptionalShare;

  final double planAdherenceVolatility;
  final double savingsRegularity;
  final double planAdherenceDelta;
  final double unallocatedShare;

  /// Maps to the exact feature names the model was trained on.
  Map<String, double> toFeatures() => {
        'essential_coverage': essentialCoverage,
        'plan_adherence': planAdherence,
        'savings_rate': savingsRate,
        'optional_spend_share': optionalSpendShare,
        'rejected_purchases': rejectedPurchases.toDouble(),
        'withdrawals': withdrawals.toDouble(),
        'revisions_count': revisionsCount.toDouble(),
        'purchases_essential': purchasesEssential.toDouble(),
        'purchases_optional': purchasesOptional.toDouble(),
        'quests_completed': questsCompleted.toDouble(),
        'quest_outcome_score': questOutcomeScore,
        'spend_to_income_ratio': 1.0 - savingsRate,
        'unallocated_share': unallocatedShare,
        'avg_essential_coverage_w': avgEssentialCoverage ?? essentialCoverage,
        'avg_plan_adherence_w': avgPlanAdherence ?? planAdherence,
        'avg_savings_rate_w': avgSavingsRate ?? savingsRate,
        'avg_optional_share_w': avgOptionalShare ?? optionalSpendShare,
        'plan_adherence_volatility': planAdherenceVolatility,
        'savings_regularity': savingsRegularity,
        'plan_adherence_delta_filled': planAdherenceDelta,
      };
}

// ---------------------------------------------------------------------------
// Rules — the part that decides
// ---------------------------------------------------------------------------

/// The deterministic advisor.
///
/// This is where the boundary between «model» and «product» is drawn. A model
/// produces a score; this class turns scores into decisions, and it is the only
/// thing allowed to.
///
/// The model may never change a balance, block a purchase, affect the cat or
/// alter the goal ETA. It picks wording, and only where the rules are
/// indifferent. See docs/adr/0001-ml-may-not-touch-the-economy.md.
abstract final class RuleBasedHints {
  static const _hints = <String, Hint>{
    'essentials_first': Hint(
      'essentials_first',
      'Котик остался голодным: обязательное не закрыто.',
      'В следующем плане поставь еду и уход первыми — так на желаемое тоже останется.',
      'rule',
    ),
    'saving_but_hungry': Hint(
      'saving_but_hungry',
      'Копилка растёт, но котику не хватило еды.',
      'Сначала закрой обязательное, а в копилку отложи то, что осталось.',
      'rule',
    ),
    'try_cheaper': Hint(
      'try_cheaper',
      'Монет не хватило на покупку.',
      'Можно выбрать вариант подешевле или подождать следующий период — это не ошибка.',
      'rule',
    ),
    'plan_overspent': Hint(
      'plan_overspent',
      'Ты потратил на желаемое больше, чем планировал.',
      'Попробуй перенести одну необязательную покупку на следующий период.',
      'rule',
    ),
    'start_saving': Hint(
      'start_saving',
      'В этот раз в копилку ничего не попало.',
      'Отложи хотя бы 10 монет — цель сразу станет ближе.',
      'rule',
    ),
    'steady_progress': Hint(
      'steady_progress',
      'Ты уверенно идёшь к цели.',
      'Посмотри, сколько периодов осталось до цели — совсем немного.',
      'rule',
    ),
    'keep_going': Hint(
      'keep_going',
      'План и факт почти совпали, и ты отложил часть монет.',
      'Так держать — попробуй в следующем периоде отложить чуть больше.',
      'rule',
    ),
    'explore_steady': Hint(
      'explore_steady',
      'Решения пока получаются очень разными.',
      'Попробуй составить план и придерживаться его весь период — так проще увидеть результат.',
      'rule',
    ),
  };

  /// Hints where the rules have no strong opinion, so a model may refine them.
  static const ambiguous = {'keep_going', 'steady_progress'};

  static const _bySegment = <Segment, String>{
    Segment.spender: 'plan_overspent',
    Segment.saver: 'saving_but_hungry',
    Segment.explorer: 'explore_steady',
    Segment.planner: 'steady_progress',
  };

  /// Ordering encodes the pedagogy: an uncovered essential is always the most
  /// important thing to say, whatever else happened in the period.
  static Hint forSnapshot(PeriodSnapshot s) {
    if (s.essentialCoverage < 0.85) {
      return s.savingsRate > 0.25
          ? _hints['saving_but_hungry']!
          : _hints['essentials_first']!;
    }
    if (s.rejectedPurchases > 0) return _hints['try_cheaper']!;
    if (s.planAdherence < 0.60) return _hints['plan_overspent']!;
    if (s.savingsRate <= 0.0) return _hints['start_saving']!;
    if (s.planAdherence >= 0.80 && s.savingsRate > 0.15) {
      return _hints['steady_progress']!;
    }
    return _hints['keep_going']!;
  }

  static Hint? forSegment(Segment segment) {
    final id = _bySegment[segment];
    if (id == null) return null;
    final hint = _hints[id];
    if (hint == null) return null;
    return Hint(hint.id, hint.text, hint.nextStep, 'model');
  }
}

// ---------------------------------------------------------------------------
// Inference
// ---------------------------------------------------------------------------

/// Loads the exported ONNX model and predicts the behaviour segment.
///
/// Every failure path returns [Segment.unknown] rather than throwing: a
/// missing, corrupt or slow model must not break the game loop, because the
/// game loop is the mandatory scenario and the model is not.
class BehaviourSegmentModel {
  BehaviourSegmentModel._(this._session, this._card);

  final OrtSession _session;
  final ModelCard _card;

  ModelCard get card => _card;

  static const _modelAsset = 'assets/models/behaviour_segment.onnx';
  static const _cardAsset = 'assets/models/behaviour_segment.json';

  /// Returns null when the model cannot be loaded — callers fall back to rules.
  static Future<BehaviourSegmentModel?> loadOrNull() async {
    try {
      OrtEnv.instance.init();

      final cardJson = await rootBundle.loadString(_cardAsset);
      final card = ModelCard.fromJson(
        jsonDecode(cardJson) as Map<String, dynamic>,
      );

      final bytes = (await rootBundle.load(_modelAsset)).buffer.asUint8List();

      final options = OrtSessionOptions()
        // One thread: the model is a few hundred kilobytes and the ТЗ targets a
        // 3 GB device. Spinning up a pool costs more than the inference.
        ..setIntraOpNumThreads(1)
        ..setInterOpNumThreads(1);

      return BehaviourSegmentModel._(
        OrtSession.fromBuffer(bytes, options),
        card,
      );
    } catch (_) {
      return null;
    }
  }

  /// Predicts the segment, or abstains.
  ///
  /// Abstains when the period is outside the model's validated range. Archetypes
  /// converge as a child learns — held-out accuracy falls from 0.89 at period 3
  /// to 0.54 at period 12 — so past the horizon the honest answer is «I don't
  /// know», and the rule-based hint is the right thing to show anyway.
  Segment predict(PeriodSnapshot snapshot) {
    final horizon = _card.maxPeriodNo;
    if (horizon != null &&
        _card.abstainOutsideRange &&
        snapshot.periodsCompleted > horizon) {
      return Segment.unknown;
    }

    try {
      final features = snapshot.toFeatures();

      // Built strictly in the card's order. This is the single most likely way
      // to ship a silently broken model, so it is asserted rather than assumed.
      final vector = Float32List(_card.featureNames.length);
      for (var i = 0; i < _card.featureNames.length; i++) {
        final name = _card.featureNames[i];
        final value = features[name];
        if (value == null) {
          assert(false, 'missing feature "$name" for ${_card.name}');
          return Segment.unknown;
        }
        vector[i] = value;
      }

      final input = OrtValueTensor.createTensorWithDataList(
        vector,
        [1, vector.length],
      );
      final outputs = _session.run(
        OrtRunOptions(),
        {_session.inputNames.first: input},
      );
      input.release();

      final label = (outputs.first?.value as List).first.toString();
      for (final output in outputs) {
        output?.release();
      }
      return _parseSegment(label);
    } catch (_) {
      return Segment.unknown;
    }
  }

  static Segment _parseSegment(String label) => switch (label) {
        'planner' => Segment.planner,
        'spender' => Segment.spender,
        'saver' => Segment.saver,
        'explorer' => Segment.explorer,
        _ => Segment.unknown,
      };

  void dispose() {
    _session.release();
    OrtEnv.instance.release();
  }
}

// ---------------------------------------------------------------------------
// What the Советник screen calls
// ---------------------------------------------------------------------------

/// Entry point for the «Советник» section.
///
/// Note the shape: the model is consulted, and then the rules decide. An
/// uncovered essential always produces the essentials hint, whatever the model
/// thinks.
class Advisor {
  const Advisor(this._model);

  final BehaviourSegmentModel? _model;

  /// True when a model is loaded and personalising wording. Useful for the
  /// adult section, which should be able to state plainly what the app is doing.
  bool get isPersonalised => _model != null;

  Hint hintFor(PeriodSnapshot snapshot) {
    final ruleHint = RuleBasedHints.forSnapshot(snapshot);

    // The model may only refine wording where the rules are indifferent.
    if (!RuleBasedHints.ambiguous.contains(ruleHint.id)) return ruleHint;

    final segment = _model?.predict(snapshot) ?? Segment.unknown;
    if (segment == Segment.unknown) return ruleHint;

    return RuleBasedHints.forSegment(segment) ?? ruleHint;
  }

  /// Periods-to-goal, ТЗ §2.5.7.
  ///
  /// A plain formula on purpose, and deliberately not a model: the number is
  /// shown to a seven-year-old, who must be able to check it —
  /// «осталось 210 монет, откладываю по 30, значит семь раз». A more accurate
  /// number that cannot be explained is worse here than a less accurate one
  /// that can. See docs/ml-cards/goal_reachability.md.
  ///
  /// Returns null when nothing has been deposited yet: showing «∞ периодов» to
  /// a child is useless and discouraging, so the app invites a first deposit
  /// instead.
  static int? periodsToGoal({
    required int goalCost,
    required int saved,
    required int totalDeposited,
    required int periodsWithDeposit,
  }) {
    if (totalDeposited <= 0 || periodsWithDeposit <= 0) return null;
    final remaining = math.max(0, goalCost - saved);
    if (remaining == 0) return 0;
    final averageDeposit = totalDeposited / periodsWithDeposit;
    return (remaining / averageDeposit).ceil();
  }
}
