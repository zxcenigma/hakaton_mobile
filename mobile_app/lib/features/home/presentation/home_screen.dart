import 'dart:math' as math;
import 'dart:async';
import 'package:flutter/material.dart';
import '../../../app/navigation/app_router.dart';
import '../../../app/navigation/app_sections.dart';
import '../../../app/theme/app_theme.dart';
import '../../../shared/widgets/round_navigation_button.dart';
import 'widgets/pet_illustration.dart';
import 'widgets/pet_skin.dart';
import 'widgets/stage_background.dart';
import 'widgets/deposit_sheet.dart';
import 'widgets/falling_coins_icon.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with TickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _slot;
  late final AnimationController _coins;
  int _balance = 0;
  int _previousBalance = 0;
  int _lastDeposit = 0;
  Timer? _depositNoticeTimer;
  bool _depositBusy = false;
  bool _foreground = true;
  bool get _reduceMotion => MediaQuery.disableAnimationsOf(context);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _slot = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 420),
    );
    _coins = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    for (final controller in [_slot, _coins]) {
      if (!_foreground && controller.isAnimating) {
        controller.stop(canceled: false);
      } else if (_foreground && controller.status == AnimationStatus.forward) {
        controller.forward();
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _depositNoticeTimer?.cancel();
    _slot.dispose();
    _coins.dispose();
    super.dispose();
  }

  Future<void> _deposit() async {
    if (_depositBusy || !_foreground) return;
    setState(() {
      _depositBusy = true;
    });
    try {
      if (_reduceMotion) {
        _slot.value = 1;
      } else {
        await _slot.forward(from: 0).orCancel;
      }
      if (!mounted) return;
      final amount = await showModalBottomSheet<int>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        backgroundColor: AppPalette.stageBackground,
        builder: (_) => const DepositSheet(),
      );
      if (!mounted) return;
      if (amount != null) {
        if (!_reduceMotion) await _coins.forward(from: 0).orCancel;
        if (!mounted) return;
        setState(() {
          _previousBalance = _balance;
          _balance += amount;
          _lastDeposit = amount;
        });
        _depositNoticeTimer?.cancel();
        _depositNoticeTimer = Timer(const Duration(seconds: 7), () {
          if (mounted) setState(() => _lastDeposit = 0);
        });
      }
    } on TickerCanceled {
      // Disposal cancels the in-flight presentation, without adding money.
    } finally {
      if (mounted) {
        _slot.value = 0;
        _coins.value = 0;
        setState(() => _depositBusy = false);
      }
    }
  }

  PetSkin _skin = PetSkin.base;

  void _showSkins() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * 0.65,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  'Гардероб',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              for (final skin in PetSkin.values)
                Semantics(
                  selected: _skin == skin,
                  child: ListTile(
                    selected: _skin == skin,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(20),
                    ),
                    leading: ExcludeSemantics(
                      child: SizedBox.square(
                        dimension: 56,
                        child: PetIllustration(skin: skin, preview: true),
                      ),
                    ),
                    title: Text(skin.label),
                    trailing: _skin == skin
                        ? const Icon(Icons.check_circle)
                        : null,
                    onTap: () {
                      setState(() => _skin = skin);
                      Navigator.of(context).pop();
                    },
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildControls(BuildContext context, double buttonSize) {
    final captionHeight = MediaQuery.textScalerOf(context).scale(11) * 2.4;
    Widget caption(String text) => ExcludeSemantics(
      child: SizedBox(
        height: captionHeight,
        child: Center(
          child: Text(
            text,
            textAlign: TextAlign.center,
            maxLines: 2,
            style: const TextStyle(
              color: AppPalette.ceramic,
              fontSize: 11,
              height: 1.2,
            ),
          ),
        ),
      ),
    );
    Widget navigation(int number) => Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        RoundNavigationButton(
          number: number,
          diameter: buttonSize,
          onPressed: () => AppRouter.openExample(context, number),
        ),
        caption(AppSections.title(number)),
      ],
    );
    return LayoutBuilder(
      builder: (context, area) {
        final centerWidth = math.min(
          buttonSize + 44,
          area.maxWidth - buttonSize * 2 - 33.6,
        );
        final rowHeight = buttonSize + 12 + captionHeight + 8;
        final lift = buttonSize / 2;
        final sideOffset = centerWidth / 2 + 16.8 + buttonSize / 2;
        final middle = area.maxWidth / 2;
        return SizedBox(
          height: rowHeight + lift + buttonSize + captionHeight,
          child: Stack(
            children: [
              for (final number in [1, 2, 3, 4])
                Positioned(
                  left:
                      middle +
                      (number < 3 ? -1 : 1) * sideOffset -
                      buttonSize / 2,
                  top: lift + (number.isEven ? rowHeight : 0),
                  width: buttonSize,
                  child: navigation(number),
                ),
              Positioned(
                top: 0,
                left: middle - centerWidth / 2,
                width: centerWidth,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox.square(
                      dimension: buttonSize + 12,
                      child: IconButton.filled(
                        tooltip: 'Пополнить копилку',
                        onPressed: _depositBusy ? null : _deposit,
                        style: IconButton.styleFrom(
                          backgroundColor: AppPalette.darkGold,
                          foregroundColor: AppPalette.gold,
                          side: BorderSide(
                            color: AppPalette.gold.withValues(alpha: 0.6),
                          ),
                        ),
                        icon: const FallingCoinsIcon(),
                      ),
                    ),
                    caption('Пополнить'),
                  ],
                ),
              ),
              Positioned(
                top: rowHeight,
                left: middle - centerWidth / 2,
                width: centerWidth,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox.square(
                      dimension: buttonSize + 12,
                      child: IconButton.filled(
                        tooltip: 'Гардероб',
                        onPressed: _showSkins,
                        style: IconButton.styleFrom(
                          backgroundColor: AppPalette.darkGold,
                          foregroundColor: AppPalette.gold,
                          side: BorderSide(
                            color: AppPalette.gold.withValues(alpha: 0.6),
                          ),
                        ),
                        icon: const Icon(Icons.checkroom_rounded, size: 32),
                      ),
                    ),
                    caption('Гардероб'),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Stack(
      children: [
        const Positioned.fill(child: StageBackground()),
        SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final inset = constraints.maxWidth < 360 ? 16.0 : 24.0;
              final buttonSize = math.max(
                56.0,
                MediaQuery.textScalerOf(context).scale(18) + 24,
              );
              final captionHeight =
                  MediaQuery.textScalerOf(context).scale(11) * 2.4;
              final minHeight =
                  buttonSize * 2.5 +
                  captionHeight * 2 +
                  24 +
                  32 +
                  120 +
                  MediaQuery.textScalerOf(context).scale(14) * 1.4 +
                  8;
              return SingleChildScrollView(
                child: SizedBox(
                  height: math.max(constraints.maxHeight, minHeight),
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(inset, 12, inset, 20),
                    child: Column(
                      children: [
                        Expanded(
                          child: LayoutBuilder(
                            builder: (context, area) {
                              final compact = area.maxHeight < 240;
                              final balanceRow = Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Flexible(
                                    child: Semantics(
                                      label: 'Баланс копилки: $_balance рублей',
                                      liveRegion: true,
                                      child: ExcludeSemantics(
                                        child: TweenAnimationBuilder<double>(
                                          tween: Tween(
                                            begin: _previousBalance.toDouble(),
                                            end: _balance.toDouble(),
                                          ),
                                          duration: _reduceMotion
                                              ? Duration.zero
                                              : const Duration(
                                                  milliseconds: 900,
                                                ),
                                          builder: (_, value, _) => Text(
                                            'Баланс · ${value.round()} ₽',
                                            style: TextStyle(
                                              color: AppPalette.gold,
                                              fontSize: compact ? 14 : 24,
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              );
                              final noticeHeight =
                                  MediaQuery.textScalerOf(context).scale(14) *
                                      1.4 +
                                  8;
                              final header = Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  balanceRow,
                                  SizedBox(
                                    height: noticeHeight,
                                    child: _lastDeposit == 0
                                        ? null
                                        : Center(
                                            child:
                                                TweenAnimationBuilder<double>(
                                                  key: ValueKey(_balance),
                                                  tween: Tween(
                                                    begin: 0,
                                                    end: 1,
                                                  ),
                                                  duration: _reduceMotion
                                                      ? Duration.zero
                                                      : const Duration(
                                                          milliseconds: 350,
                                                        ),
                                                  builder: (_, value, child) =>
                                                      Opacity(
                                                        opacity: value,
                                                        child: child,
                                                      ),
                                                  child: Text(
                                                    '+$_lastDeposit ₽',
                                                    style: const TextStyle(
                                                      color: Color(0xFF8FDEA5),
                                                      fontSize: 14,
                                                      fontWeight:
                                                          FontWeight.w600,
                                                      shadows: [
                                                        Shadow(
                                                          color: Color(
                                                            0x6676D993,
                                                          ),
                                                          blurRadius: 12,
                                                        ),
                                                      ],
                                                    ),
                                                  ),
                                                ),
                                          ),
                                  ),
                                ],
                              );
                              final pet = Center(
                                child: Padding(
                                  padding: const EdgeInsets.all(8),
                                  child: PetIllustration(
                                    skin: _skin,
                                    slot: _slot,
                                    coins: _coins,
                                  ),
                                ),
                              );
                              final naturalSize = math.min(
                                340.0,
                                area.maxWidth - 16,
                              );
                              final headerHeight = math.max(
                                48.0,
                                MediaQuery.textScalerOf(
                                      context,
                                    ).scale(compact ? 14 : 24) *
                                    1.3,
                              );
                              final roomForOverlay =
                                  area.maxHeight >=
                                  naturalSize +
                                      2 * (headerHeight + noticeHeight) +
                                      16;
                              return Stack(
                                children: [
                                  if (roomForOverlay) ...[
                                    Positioned.fill(child: pet),
                                    Align(
                                      alignment: Alignment.topCenter,
                                      child: header,
                                    ),
                                  ] else
                                    Column(
                                      children: [
                                        header,
                                        Expanded(child: pet),
                                      ],
                                    ),
                                ],
                              );
                            },
                          ),
                        ),
                        _buildControls(context, buttonSize),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
    ),
  );
}
