import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../../app/theme/app_theme.dart';
import 'pet_skin.dart';

class PetIllustration extends StatefulWidget {
  const PetIllustration({
    super.key,
    this.skin = PetSkin.base,
    this.preview = false,
    this.slot = const AlwaysStoppedAnimation(0),
    this.coins = const AlwaysStoppedAnimation(0),
  });

  final PetSkin skin;
  final bool preview;
  final Animation<double> slot;
  final Animation<double> coins;

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
      duration: const Duration(seconds: 8),
    );
    _reaction = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 750),
    );
    _repaint = Listenable.merge([_idle, _reaction, widget.slot, widget.coins]);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = widget.preview || MediaQuery.disableAnimationsOf(context);
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
      button: !widget.preview,
      label: 'Кот-копилка, ${widget.skin.label}',
      hint: 'Погладить котика',
      onTap: widget.preview ? null : _pet,
      child: GestureDetector(
        onTap: widget.preview ? null : _pet,
        excludeFromSemantics: true,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 340, maxHeight: 360),
          child: AspectRatio(
            aspectRatio: 1,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (!widget.preview)
                  const RepaintBoundary(
                    key: ValueKey('pet-podium'),
                    child: CustomPaint(painter: _PodiumPainter()),
                  ),
                RepaintBoundary(
                  child: CustomPaint(
                    isComplex: true,
                    willChange: !widget.preview,
                    painter: _CatPainter(
                      skin: widget.skin,
                      slot: widget.slot,
                      coins: widget.coins,
                      idle: _idle,
                      reaction: _reaction,
                      repaint: _repaint,
                      reduceMotion: _reduceMotion,
                      smiling: _smiling,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _CatPainter extends CustomPainter {
  _CatPainter({
    required this.skin,
    required this.slot,
    required this.coins,
    required this.idle,
    required this.reaction,
    required Listenable repaint,
    required this.reduceMotion,
    required this.smiling,
  }) : super(repaint: repaint);

  final PetSkin skin;
  final Animation<double> slot;
  final Animation<double> coins;
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

    // Vector antialiasing avoids an extra full-character image filter per frame.
    final fill = Paint()..isAntiAlias = true;
    final line = Paint()
      ..isAntiAlias = true
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    void oval(Rect rect, Color color) {
      canvas.drawOval(rect, fill..color = color);
    }

    final phase = reduceMotion ? 0.0 : idle.value;
    final breath = math.sin(phase * math.pi * 4);
    final wag = math.sin(phase * math.pi * 4) * 0.16;
    final hop = reduceMotion ? 0.0 : math.sin(reaction.value * math.pi);
    final happy = smiling || hop > 0.1;
    // Blink once in each eight-second cycle; stay open the rest of the time.
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
        ..color = AppPalette.ceramicShade
        ..strokeWidth = 24,
    );

    canvas.restore();

    _drawBody(canvas, fill, oval);
    oval(const Rect.fromLTWH(119, 197, 84, 70), AppPalette.surface);

    final ears = Path()
      ..moveTo(76, 125)
      ..quadraticBezierTo(67, 47, 84, 46)
      ..quadraticBezierTo(97, 47, 127, 79)
      ..lineTo(198, 79)
      ..quadraticBezierTo(232, 45, 244, 48)
      ..quadraticBezierTo(255, 52, 243, 132)
      ..close();
    canvas.drawPath(ears, fill..color = AppPalette.ceramic);
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
    _drawHood(canvas, fill, oval);
    oval(const Rect.fromLTWH(68, 75, 184, 141), AppPalette.ceramic);
    if (skin == PetSkin.frog || skin == PetSkin.elephant) {
      oval(const Rect.fromLTWH(68, 75, 184, 141), costumeColor);
      oval(const Rect.fromLTWH(86, 108, 148, 101), AppPalette.ceramic);
    }

    _drawHeadwear(canvas, fill, line, oval);

    _drawFace(canvas, fill, line, oval, happy: happy, blink: blink);
    oval(const Rect.fromLTWH(92, 249, 58, 32), AppPalette.ceramic);
    oval(const Rect.fromLTWH(173, 249, 58, 32), AppPalette.ceramic);
    line
      ..color = AppPalette.ceramicShade
      ..strokeWidth = 2;
    for (final x in [111.0, 122.0, 193.0, 204.0]) {
      canvas.drawLine(Offset(x, 265), Offset(x, 273), line);
    }
    _drawAccessories(canvas, fill, line, oval);
    // Raised beckoning paw, attached to the same breathing/hop transform.
    oval(const Rect.fromLTWH(224, 161, 35, 79), costumeColor);
    oval(const Rect.fromLTWH(225, 153, 34, 37), AppPalette.ceramic);
    oval(const Rect.fromLTWH(233, 163, 16, 17), AppPalette.pink);
    // Ceramic highlights.
    oval(
      const Rect.fromLTWH(91, 108, 9, 22),
      Colors.white.withValues(alpha: 0.55),
    );
    oval(
      const Rect.fromLTWH(104, 221, 6, 22),
      Colors.white.withValues(alpha: 0.3),
    );
    _drawDeposit(canvas);
    canvas.restore(); // Cat transform.
    canvas.restore(); // Canvas coordinates.
  }

  void _drawDeposit(Canvas canvas) {
    if (slot.value <= 0) return;
    final opening = Curves.easeInOut.transform(slot.value);
    final bounds = Rect.fromCenter(
      center: const Offset(160, 79),
      width: (58 / 2.5) * opening,
      height: 5,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(bounds.inflate(0.8), const Radius.circular(3)),
      Paint()
        ..isAntiAlias = true
        ..color = AppPalette.gold,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(bounds, const Radius.circular(2.5)),
      Paint()
        ..isAntiAlias = true
        ..color = AppPalette.stageBackground,
    );
    if (coins.value <= 0 || coins.value >= 1) return;
    canvas.save();
    canvas.clipRect(const Rect.fromLTWH(120, -40, 80, 120), doAntiAlias: true);
    for (var i = 0; i < 5; i++) {
      final progress = (coins.value * 1.7 - i * 0.16).clamp(0.0, 1.0);
      if (progress <= 0 || progress >= 1) continue;
      final y = -18 + 114 * Curves.easeInQuad.transform(progress);
      final x = 160 + math.sin(progress * math.pi * 2 + i) * 2 * (1 - progress);
      canvas.drawOval(
        Rect.fromCenter(
          center: Offset(x, y),
          width: 10 + 4 * math.cos(progress * math.pi).abs(),
          height: 14,
        ),
        Paint()
          ..isAntiAlias = true
          ..shader = const LinearGradient(
            colors: [
              AppPalette.ceramic,
              AppPalette.gold,
              AppPalette.ceramicShade,
            ],
          ).createShader(Rect.fromLTWH(x - 7, y - 7, 14, 14)),
      );
      canvas.drawLine(
        Offset(x, y - 4),
        Offset(x, y + 4),
        Paint()
          ..isAntiAlias = true
          ..strokeWidth = 2
          ..strokeCap = StrokeCap.round
          ..color = AppPalette.darkGold,
      );
    }
    canvas.restore();
  }

  void _drawFace(
    Canvas canvas,
    Paint fill,
    Paint line,
    void Function(Rect, Color) oval, {
    required bool happy,
    required double blink,
  }) {
    // Forehead tufts.
    line
      ..color = AppPalette.ceramicShade
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
    canvas.drawPath(nose, fill..color = AppPalette.podiumTop);
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
      ..color = AppPalette.podiumTop
      ..strokeWidth = 2;
    for (final dy in [-5.0, 5.0]) {
      canvas.drawLine(Offset(96, 164 + dy), Offset(68, 162 + dy * 2), line);
      canvas.drawLine(Offset(225, 164 + dy), Offset(253, 162 + dy * 2), line);
    }
  }

  Color get costumeColor => switch (skin) {
    PetSkin.base => AppPalette.ceramic,
    PetSkin.ninja => const Color(0xFF393B56),
    PetSkin.santa => const Color(0xFFBE4C64),
    PetSkin.frog => const Color(0xFF83B890),
    PetSkin.elephant => const Color(0xFF96A5BD),
  };

  void _drawBody(Canvas canvas, Paint fill, void Function(Rect, Color) oval) {
    oval(const Rect.fromLTWH(83, 154, 157, 127), costumeColor);
  }

  void _drawHood(Canvas canvas, Paint fill, void Function(Rect, Color) oval) {
    if (skin == PetSkin.elephant) {
      for (final x in [43.0, 223.0]) {
        oval(Rect.fromLTWH(x, 82, 57, 103), costumeColor);
        oval(Rect.fromLTWH(x + 9, 97, 39, 71), AppPalette.pink);
      }
    }
    if (skin == PetSkin.frog) {
      for (final x in [87.0, 198.0]) {
        oval(Rect.fromLTWH(x, 53, 40, 44), costumeColor);
        oval(Rect.fromLTWH(x + 9, 58, 22, 25), AppPalette.surface);
        oval(Rect.fromLTWH(x + 16, 63, 9, 14), AppPalette.ink);
      }
    }
  }

  void _drawHeadwear(
    Canvas canvas,
    Paint fill,
    Paint line,
    void Function(Rect, Color) oval,
  ) {
    if (skin == PetSkin.ninja) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(73, 104, 175, 20),
          const Radius.circular(8),
        ),
        fill..color = costumeColor,
      );
      final ties = Path()
        ..moveTo(240, 109)
        ..lineTo(279, 91)
        ..lineTo(268, 118)
        ..lineTo(286, 132)
        ..lineTo(242, 124)
        ..close();
      canvas.drawPath(ties, fill..color = costumeColor);
      canvas.drawCircle(
        const Offset(161, 114),
        7,
        fill..color = AppPalette.pink,
      );
    }
    if (skin == PetSkin.santa) {
      final hat = Path()
        ..moveTo(81, 93)
        ..quadraticBezierTo(130, 7, 199, 37)
        ..quadraticBezierTo(241, 43, 246, 84)
        ..lineTo(224, 81)
        ..quadraticBezierTo(212, 56, 198, 67)
        ..lineTo(225, 94)
        ..close();
      canvas.drawPath(hat, fill..color = costumeColor);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(77, 82, 155, 23),
          const Radius.circular(12),
        ),
        fill..color = AppPalette.surface,
      );
      oval(const Rect.fromLTWH(231, 71, 29, 29), AppPalette.surface);
    }
  }

  void _drawAccessories(
    Canvas canvas,
    Paint fill,
    Paint line,
    void Function(Rect, Color) oval,
  ) {
    // Collar and lucky coin keep the bank recognisable in every outfit.
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(108, 204, 105, 12),
        const Radius.circular(6),
      ),
      fill..color = const Color(0xFFBE4C64),
    );
    oval(const Rect.fromLTWH(146, 211, 30, 32), const Color(0xFFE8BD69));
    canvas.drawLine(
      const Offset(161, 219),
      const Offset(161, 234),
      line
        ..color = const Color(0xFFA47637)
        ..strokeWidth = 3,
    );
    if (skin == PetSkin.ninja || skin == PetSkin.santa) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(89, 246, 143, 14),
          const Radius.circular(5),
        ),
        fill..color = AppPalette.ink,
      );
      if (skin == PetSkin.ninja) {
        final knot = Path()
          ..moveTo(188, 252)
          ..lineTo(209, 273)
          ..lineTo(197, 277)
          ..lineTo(180, 253)
          ..close();
        canvas.drawPath(knot, fill..color = costumeColor);
      } else {
        canvas.drawRect(
          const Rect.fromLTWH(151, 246, 20, 14),
          line
            ..color = const Color(0xFFE8BD69)
            ..strokeWidth = 3,
        );
        oval(const Rect.fromLTWH(94, 266, 132, 11), AppPalette.surface);
      }
    }
    if (skin == PetSkin.frog) {
      for (final x in [111.0, 200.0]) {
        oval(Rect.fromLTWH(x, 225, 12, 17), const Color(0xFF5B9674));
      }
    }
    if (skin == PetSkin.elephant) {
      final trunk = Path()
        ..moveTo(161, 176)
        ..quadraticBezierTo(153, 201, 173, 201)
        ..quadraticBezierTo(185, 201, 184, 188);
      canvas.drawPath(
        trunk,
        line
          ..color = costumeColor
          ..strokeWidth = 15,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _CatPainter oldDelegate) =>
      oldDelegate.skin != skin ||
      oldDelegate.slot != slot ||
      oldDelegate.coins != coins ||
      oldDelegate.reduceMotion != reduceMotion ||
      oldDelegate.smiling != smiling ||
      oldDelegate.idle != idle ||
      oldDelegate.reaction != reaction;
}

/// Independent static layer: never receives the cat's animation or filter.
class _PodiumPainter extends CustomPainter {
  const _PodiumPainter();
  @override
  void paint(Canvas canvas, Size size) {
    final scale = math.min(size.width, size.height) / 320;
    canvas.save();
    canvas.translate(
      (size.width - 320 * scale) / 2,
      (size.height - 320 * scale) / 2,
    );
    canvas.scale(scale);
    // Fixed half-disc underneath the paws; only the cat reacts to touch.
    final front = Path()
      ..moveTo(24, 279)
      ..cubicTo(24, 329, 296, 329, 296, 279)
      ..close();
    canvas.drawPath(
      front,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [AppPalette.stageLight, AppPalette.podiumEdge],
        ).createShader(const Rect.fromLTWH(24, 279, 272, 40)),
    );
    const top = Rect.fromLTWH(24, 264, 272, 30);
    canvas.drawOval(
      top,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppPalette.podiumTop, AppPalette.stageLight],
        ).createShader(top),
    );
    canvas.drawOval(
      top.deflate(1),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = AppPalette.ceramic.withValues(alpha: 0.16),
    );
    canvas.drawOval(
      const Rect.fromLTWH(83, 270, 157, 16),
      Paint()
        ..color = Colors.black.withValues(alpha: 0.23)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _PodiumPainter oldDelegate) => false;
}
