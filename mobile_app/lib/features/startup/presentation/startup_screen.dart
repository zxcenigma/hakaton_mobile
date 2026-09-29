import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/app_theme.dart';
import '../../../logic/api/api.dart';
import '../../../logic/profile/profile_store.dart';
import '../../home/presentation/widgets/stage_background.dart';
import 'widgets/name_dialog.dart';

class StartupScreen extends StatefulWidget {
  const StartupScreen({super.key, required this.home, this.api, this.store});
  final Widget home;
  final ApiService? api;
  final ProfileStore? store;

  @override
  State<StartupScreen> createState() => _StartupScreenState();
}

class _StartupScreenState extends State<StartupScreen> {
  late final ApiService _api = widget.api ?? ApiService();
  late final ProfileStore _store = widget.store ?? LocalProfileStore();
  bool _running = false;
  bool _showLoading = false;
  bool _ready = false;
  bool _splashGone = false;
  double _progress = 0;
  String? _error;
  LocalProfile? _profile;
  Timer? _introTimer;

  bool get _reduceMotion => MediaQuery.disableAnimationsOf(context);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _introTimer = Timer(const Duration(milliseconds: 750), () {
        if (mounted) setState(() => _showLoading = true);
      });
      _prepare();
    });
  }

  Future<void> _preloadImages() async {
    for (final path in [
      'assets/image/logo.png',
      'assets/image/loading_page.png',
    ]) {
      if (!mounted) return;
      Object? failure;
      await precacheImage(
        AssetImage(path),
        context,
        onError: (error, _) => failure = error,
      );
      if (failure != null) throw StateError('Could not load startup artwork');
    }
    // The home tree has already been laid out offstage on the first frame.
    await WidgetsBinding.instance.endOfFrame;
  }

  Future<void> _prepare() async {
    if (_running) return;
    setState(() {
      _running = true;
      _error = null;
      _progress = .06;
    });
    var completed = 0;
    void step() {
      completed++;
      if (mounted) setState(() => _progress = .06 + completed * .28);
    }

    try {
      await Future.wait([
        _api.checkReady().then((_) => step()),
        _store.read().then((value) {
          _profile = value;
          step();
        }),
        _preloadImages().then((_) => step()),
        Future<void>.delayed(
          _reduceMotion ? Duration.zero : const Duration(milliseconds: 1800),
        ),
      ]);
      if (!mounted) return;
      setState(() {
        _progress = 1;
        _showLoading = true;
      });
      if (!_reduceMotion) {
        await Future<void>.delayed(const Duration(milliseconds: 450));
      }
      if (!mounted) return;
      if (_profile == null) {
        final accepted = await showGeneralDialog<bool>(
          context: context,
          barrierDismissible: false,
          barrierLabel: 'Знакомство',
          barrierColor: const Color(0xFF140F0B).withValues(alpha: .72),
          transitionDuration: _reduceMotion
              ? Duration.zero
              : const Duration(milliseconds: 350),
          pageBuilder: (_, _, _) => NameDialog(api: _api, store: _store),
          transitionBuilder: (_, animation, _, child) {
            final curve = CurvedAnimation(
              parent: animation,
              curve: Curves.easeOutCubic,
            );
            return FadeTransition(
              opacity: curve,
              child: SlideTransition(
                position: Tween(
                  begin: const Offset(0, .06),
                  end: Offset.zero,
                ).animate(curve),
                child: child,
              ),
            );
          },
        );
        if (!mounted || accepted != true) return;
      }
      setState(() {
        _ready = true;
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _showLoading = true;
          _error = error.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _showLoading = true;
          _error = 'Не удалось подготовить копилку. Попробуйте ещё раз.';
        });
      }
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  void dispose() {
    _introTimer?.cancel();
    if (widget.api == null) _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(
    fit: StackFit.expand,
    children: [
      // Prepare the actual home page before dismissing the splash.
      Offstage(
        offstage: !_ready,
        child: TickerMode(enabled: _ready, child: widget.home),
      ),
      if (!_splashGone)
        IgnorePointer(
          ignoring: _ready,
          child: AnimatedOpacity(
            opacity: _ready ? 0 : 1,
            duration: _reduceMotion
                ? Duration.zero
                : const Duration(milliseconds: 500),
            onEnd: () {
              if (_ready && mounted) setState(() => _splashGone = true);
            },
            child: Scaffold(
              body: Stack(
                fit: StackFit.expand,
                children: [
                  const StageBackground(),
                  SafeArea(
                    child: AnimatedSwitcher(
                      duration: _reduceMotion
                          ? Duration.zero
                          : const Duration(milliseconds: 600),
                      child: _showLoading ? _buildLoading() : _buildLogo(),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
    ],
  );

  Widget _buildLogo() => Center(
    key: const ValueKey('startup-logo'),
    child: TweenAnimationBuilder<double>(
      tween: Tween(begin: _reduceMotion ? 1 : .85, end: 1),
      duration: _reduceMotion
          ? Duration.zero
          : const Duration(milliseconds: 700),
      curve: Curves.easeOutCubic,
      builder: (_, value, child) => Opacity(
        opacity: ((value - .85) / .15).clamp(0, 1),
        child: Transform.scale(scale: value, child: child),
      ),
      child: Image.asset(
        'assets/image/logo.png',
        width: 180,
        height: 180,
        semanticLabel: 'Киса Копилка',
        filterQuality: FilterQuality.high,
      ),
    ),
  );

  Widget _buildLoading() => LayoutBuilder(
    key: const ValueKey('startup-loading'),
    builder: (context, constraints) => SingleChildScrollView(
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: constraints.maxHeight),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(28, 16, 28, 28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(
                height: (constraints.maxHeight * .48).clamp(150.0, 420.0),
                child: ExcludeSemantics(
                  child: ShaderMask(
                    blendMode: BlendMode.dstIn,
                    shaderCallback: (bounds) => const LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        Colors.transparent,
                        Colors.white,
                        Colors.white,
                        Colors.transparent,
                      ],
                      stops: [0, .14, .83, 1],
                    ).createShader(bounds),
                    // Crop the reference's static text and bar; use live widgets below.
                    child: FittedBox(
                      fit: BoxFit.contain,
                      child: SizedBox(
                        width: 480,
                        child: ClipRect(
                          child: Align(
                            alignment: Alignment.topCenter,
                            heightFactor: .66,
                            child: Image.asset(
                              'assets/image/loading_page.png',
                              width: 480,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Киса Копилка',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w600,
                  color: AppPalette.ceramic,
                  letterSpacing: -.8,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Большие мечты начинаются с малого',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 13,
                  color: AppPalette.ceramicShade,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 18),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 320),
                child: Column(
                  children: [
                    Semantics(
                      label: 'Подготовка приложения',
                      value: '${(_progress * 100).round()}%',
                      child: TweenAnimationBuilder<double>(
                        tween: Tween(begin: 0, end: _progress),
                        duration: _reduceMotion
                            ? Duration.zero
                            : const Duration(milliseconds: 450),
                        curve: Curves.easeOutCubic,
                        builder: (_, value, _) => ClipRRect(
                          borderRadius: BorderRadius.circular(20),
                          child: SizedBox(
                            height: 7,
                            child: ColoredBox(
                              color: AppPalette.gold.withValues(alpha: .12),
                              child: Align(
                                alignment: Alignment.centerLeft,
                                child: FractionallySizedBox(
                                  widthFactor: value,
                                  child: Container(
                                    decoration: BoxDecoration(
                                      borderRadius: BorderRadius.circular(20),
                                      gradient: const LinearGradient(
                                        colors: [
                                          Color(0xFFB9813D),
                                          Color(0xFFFFE5A5),
                                        ],
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Semantics(
                      liveRegion: true,
                      child: Text(
                        _error ??
                            (_progress == 1
                                ? 'Всё готово'
                                : 'Готовим вашу копилку…'),
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 14,
                          height: 1.5,
                          color: _error == null
                              ? AppPalette.ceramicShade
                              : const Color(0xFFF0B7A4),
                        ),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      OutlinedButton.icon(
                        onPressed: _running ? null : _prepare,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Попробовать ещё раз'),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppPalette.gold,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 20,
                            vertical: 14,
                          ),
                          side: BorderSide(
                            color: AppPalette.gold.withValues(alpha: .35),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
