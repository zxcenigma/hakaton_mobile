import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../../app/theme/app_theme.dart';

/// A top-down cat running in a circle, reaching towards its own curled tail.
class ChasingCat extends StatefulWidget {
  const ChasingCat({super.key, this.running = true, this.size = 64});
  final bool running;
  final double size;

  @override
  State<ChasingCat> createState() => _ChasingCatState();
}

class _ChasingCatState extends State<ChasingCat>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _run = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  );
  bool _foreground = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _foreground =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
  }

  void _update() {
    final animate =
        widget.running &&
        _foreground &&
        TickerMode.valuesOf(context).enabled &&
        !MediaQuery.disableAnimationsOf(context);
    if (animate && !_run.isAnimating) _run.repeat();
    if (!animate) _run.stop();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _update();
  }

  @override
  void didUpdateWidget(ChasingCat oldWidget) {
    super.didUpdateWidget(oldWidget);
    _update();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _update();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _run.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: RepaintBoundary(
      child: SizedBox.square(
        dimension: widget.size,
        child: CustomPaint(painter: _CatPainter(_run)),
      ),
    ),
  );
}

class _CatPainter extends CustomPainter {
  _CatPainter(this.animation) : super(repaint: animation);
  final Animation<double> animation;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 100, size.height / 100);
    canvas.translate(50, 50);
    canvas.drawCircle(
      Offset.zero,
      36,
      Paint()
        ..color = AppPalette.gold.withValues(alpha: 0.09)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5,
    );
    canvas.rotate(animation.value * math.pi * 2);
    final stride = math.sin(animation.value * math.pi * 16) * 4;
    final fur = Paint()..color = const Color(0xFFF3D8A7);
    final shade = Paint()..color = const Color(0xFFC79D68);
    // Alternating front/back paw positions make a gait, not a rotating icon.
    for (final side in [-1.0, 1.0]) {
      canvas.drawOval(
        Rect.fromCenter(
          center: Offset(25 + side * 11, -5 + side * stride),
          width: 10,
          height: 15,
        ),
        shade,
      );
      canvas.drawOval(
        Rect.fromCenter(
          center: Offset(22 + side * 10, 17 - side * stride),
          width: 10,
          height: 14,
        ),
        fur,
      );
    }
    final tail = Path()
      ..moveTo(20, 18)
      ..cubicTo(12, 39, -22, 43, -31, 19)
      ..cubicTo(-39, 0, -28, -18, -13, -22);
    canvas.drawPath(
      tail,
      Paint()
        ..color = const Color(0xFFE9C896)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 9
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawOval(
      Rect.fromCenter(center: const Offset(24, 6), width: 25, height: 38),
      fur,
    );
    for (final y in [-1.0, 6.0, 13.0]) {
      canvas.drawLine(
        Offset(31, y),
        Offset(36, y + 2),
        Paint()
          ..color = const Color(0xFFC79D68)
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.save();
    canvas.translate(18, -19);
    canvas.rotate(-0.55);
    canvas.drawPath(
      Path()
        ..moveTo(-13, -2)
        ..lineTo(-13, -16)
        ..lineTo(-2, -10)
        ..close(),
      fur,
    );
    canvas.drawPath(
      Path()
        ..moveTo(13, -2)
        ..lineTo(13, -16)
        ..lineTo(2, -10)
        ..close(),
      fur,
    );
    canvas.drawCircle(Offset.zero, 15, fur);
    canvas.drawPath(
      Path()
        ..moveTo(-11, -7)
        ..lineTo(-11, -12)
        ..lineTo(-6, -9)
        ..close(),
      Paint()..color = AppPalette.rose,
    );
    canvas.drawPath(
      Path()
        ..moveTo(11, -7)
        ..lineTo(11, -12)
        ..lineTo(6, -9)
        ..close(),
      Paint()..color = AppPalette.rose,
    );
    final face = Paint()..color = const Color(0xFF523720);
    canvas.drawCircle(const Offset(-6, -4), 1.5, face);
    canvas.drawCircle(const Offset(6, -4), 1.5, face);
    canvas.drawOval(
      Rect.fromCenter(center: const Offset(0, -10), width: 4, height: 3),
      face,
    );
    canvas.drawArc(
      Rect.fromCircle(center: Offset.zero, radius: 14),
      0.25,
      2.6,
      false,
      Paint()
        ..color = const Color(0xFFA54335)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
    canvas.drawCircle(const Offset(0, 16), 3, Paint()..color = AppPalette.gold);
    canvas.restore();
    canvas.restore();
  }

  @override
  bool shouldRepaint(_CatPainter oldDelegate) =>
      oldDelegate.animation != animation;
}
