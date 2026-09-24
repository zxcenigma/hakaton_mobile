import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../../app/theme/app_theme.dart';

class PetIllustration extends StatefulWidget {
  const PetIllustration({super.key});

  @override
  State<PetIllustration> createState() => _PetIllustrationState();
}

class _PetIllustrationState extends State<PetIllustration>
    with TickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _idle;
  late final AnimationController _reaction;
  late final Listenable _repaint;
  bool _reduceMotion = false;
  bool _visible = true;
  bool _foreground = true;
  bool _smiling = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _foreground =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    _idle = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 6),
    );
    _reaction = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 750),
    );
    _repaint = Listenable.merge([_idle, _reaction]);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = MediaQuery.disableAnimationsOf(context);
    _visible = TickerMode.valuesOf(context).enabled;
    _updateMotion();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _updateMotion();
  }

  void _updateMotion() {
    if (!_reduceMotion && _visible && _foreground) {
      if (!_idle.isAnimating) _idle.repeat();
    } else {
      _idle.stop();
      _reaction.reset();
    }
  }

  void _pet() {
    if (!_foreground || !_visible) return;
    if (_reduceMotion) {
      setState(() => _smiling = !_smiling);
    } else {
      _reaction.forward(from: 0);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _idle.dispose();
    _reaction.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      image: true,
      button: true,
      label: 'Лавандовый котик с розовыми щёчками',
      hint: 'Погладить котика',
      onTap: _pet,
      child: GestureDetector(
        onTap: _pet,
        excludeFromSemantics: true,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 340, maxHeight: 360),
          child: AspectRatio(
            aspectRatio: 1,
            child: RepaintBoundary(
              child: CustomPaint(
                painter: _CatPainter(
                  idle: _idle,
                  reaction: _reaction,
                  repaint: _repaint,
                  reduceMotion: _reduceMotion,
                  smiling: _smiling,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CatPainter extends CustomPainter {
  _CatPainter({
    required this.idle,
    required this.reaction,
    required Listenable repaint,
    required this.reduceMotion,
    required this.smiling,
  }) : super(repaint: repaint);

  final Animation<double> idle;
  final Animation<double> reaction;
  final bool reduceMotion;
  final bool smiling;

  @override
  void paint(Canvas canvas, Size size) {
    final scale = math.min(size.width, size.height) / 320;
    canvas.save();
    canvas.translate(
      (size.width - 320 * scale) / 2,
      (size.height - 320 * scale) / 2,
    );
    canvas.scale(scale);

    final fill = Paint()..isAntiAlias = true;
    final line = Paint()
      ..isAntiAlias = true
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    void oval(Rect rect, Color color) {
      canvas.drawOval(rect, fill..color = color);
    }

    // Quiet backdrop and a grounding shadow.
    oval(
      const Rect.fromLTWH(20, 20, 280, 280),
      AppPalette.lavender.withValues(alpha: 0.5),
    );
    oval(
      const Rect.fromLTWH(71, 272, 185, 20),
      AppPalette.purple.withValues(alpha: 0.09),
    );
    canvas.drawCircle(const Offset(270, 73), 9, fill..color = AppPalette.mint);
    canvas.drawCircle(const Offset(41, 196), 6, fill..color = AppPalette.pink);

    final phase = reduceMotion ? 0.0 : idle.value;
    final breath = math.sin(phase * math.pi * 4);
    final wag = math.sin(phase * math.pi * 4) * 0.16;
    final hop = reduceMotion ? 0.0 : math.sin(reaction.value * math.pi);
    final happy = smiling || hop > 0.1;
    // Blink once in each six-second cycle; stay open the rest of the time.
    final blink = phase > 0.76 && phase < 0.81
        ? math.sin((phase - 0.76) / 0.05 * math.pi)
        : 0.0;

    // Anchor breathing at the paws. The backdrop stays still.
    canvas.save();
    canvas.translate(160, 279 - hop * 20);
    canvas.scale(1 + breath * 0.008, 1 + breath * 0.012);
    canvas.translate(-160, -279);

    canvas.save();
    canvas.translate(222, 258);
    canvas.rotate(wag + hop * 0.12);
    canvas.translate(-222, -258);
    final tail = Path()
      ..moveTo(222, 258)
      ..cubicTo(288, 267, 287, 218, 269, 208);
    canvas.drawPath(
      tail,
      line
        ..color = AppPalette.petShade
        ..strokeWidth = 24,
    );

    canvas.restore();

    oval(const Rect.fromLTWH(89, 154, 145, 127), AppPalette.pet);
    oval(const Rect.fromLTWH(119, 197, 84, 70), AppPalette.lavender);

    final ears = Path()
      ..moveTo(76, 125)
      ..quadraticBezierTo(67, 47, 84, 46)
      ..quadraticBezierTo(97, 47, 127, 79)
      ..lineTo(198, 79)
      ..quadraticBezierTo(232, 45, 244, 48)
      ..quadraticBezierTo(255, 52, 243, 132)
      ..close();
    canvas.drawPath(ears, fill..color = AppPalette.pet);
    final innerEars = Path()
      ..moveTo(84, 91)
      ..lineTo(85, 62)
      ..lineTo(108, 86)
      ..close()
      ..moveTo(218, 87)
      ..lineTo(239, 64)
      ..lineTo(238, 98)
      ..close();
    canvas.drawPath(innerEars, fill..color = AppPalette.pink);
    oval(const Rect.fromLTWH(68, 75, 184, 141), AppPalette.pet);

    // Forehead tufts.
    line
      ..color = AppPalette.petShade
      ..strokeWidth = 5;
    canvas.drawLine(const Offset(146, 84), const Offset(150, 96), line);
    canvas.drawLine(const Offset(161, 82), const Offset(161, 95), line);
    canvas.drawLine(const Offset(176, 84), const Offset(172, 96), line);

    oval(const Rect.fromLTWH(86, 152, 32, 17), AppPalette.pink);
    oval(const Rect.fromLTWH(205, 152, 32, 17), AppPalette.pink);
    for (final x in [119.0, 203.0]) {
      if (happy) {
        final eye = Path()
          ..moveTo(x - 7, 141)
          ..quadraticBezierTo(x, 130, x + 7, 141);
        canvas.drawPath(
          eye,
          line
            ..color = AppPalette.ink
            ..strokeWidth = 3,
        );
      } else {
        canvas.save();
        canvas.translate(x, 139);
        canvas.scale(1.0, 1 - blink * 0.92);
        oval(const Rect.fromLTWH(-7, -11, 14, 22), AppPalette.ink);
        canvas.drawCircle(
          const Offset(-2, -6),
          3,
          fill..color = AppPalette.surface,
        );
        canvas.restore();
      }
    }

    final nose = Path()
      ..moveTo(154, 153)
      ..quadraticBezierTo(161, 149, 168, 153)
      ..quadraticBezierTo(168, 157, 161, 161)
      ..quadraticBezierTo(154, 157, 154, 153);
    canvas.drawPath(nose, fill..color = AppPalette.purple);
    final smile = Path()
      ..moveTo(161, 161)
      ..lineTo(161, 168)
      ..quadraticBezierTo(152, 178, 145, 169)
      ..moveTo(161, 168)
      ..quadraticBezierTo(170, 178, 177, 169);
    canvas.drawPath(
      smile,
      line
        ..color = AppPalette.ink
        ..strokeWidth = 2.5,
    );

    line
      ..color = AppPalette.purple
      ..strokeWidth = 2;
    for (final dy in [-5.0, 5.0]) {
      canvas.drawLine(Offset(96, 164 + dy), Offset(68, 162 + dy * 2), line);
      canvas.drawLine(Offset(225, 164 + dy), Offset(253, 162 + dy * 2), line);
    }
    oval(const Rect.fromLTWH(92, 249, 58, 32), AppPalette.pet);
    oval(const Rect.fromLTWH(173, 249, 58, 32), AppPalette.pet);
    line
      ..color = AppPalette.petShade
      ..strokeWidth = 2;
    for (final x in [111.0, 122.0, 193.0, 204.0]) {
      canvas.drawLine(Offset(x, 265), Offset(x, 273), line);
    }
    canvas.restore(); // Cat transform.
    canvas.restore(); // Canvas coordinates.
  }

  @override
  bool shouldRepaint(covariant _CatPainter oldDelegate) =>
      oldDelegate.reduceMotion != reduceMotion ||
      oldDelegate.smiling != smiling ||
      oldDelegate.idle != idle ||
      oldDelegate.reaction != reaction;
}
