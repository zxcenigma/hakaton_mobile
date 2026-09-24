import 'package:flutter/material.dart';

/// Three descending coins with short motion trails.
class FallingCoinsIcon extends StatelessWidget {
  const FallingCoinsIcon({super.key});

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: CustomPaint(
      size: const Size.square(34),
      painter: _CoinsIconPainter(IconTheme.of(context).color ?? Colors.white),
    ),
  );
}

class _CoinsIconPainter extends CustomPainter {
  const _CoinsIconPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 34, size.height / 34);
    final paint = Paint()
      ..color = color
      ..isAntiAlias = true
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round;
    for (final center in [
      const Offset(9, 12),
      const Offset(25, 20),
      const Offset(13, 28),
    ]) {
      canvas.drawOval(
        Rect.fromCenter(center: center, width: 10, height: 9),
        paint,
      );
      canvas.drawLine(
        center.translate(0, -1.5),
        center.translate(0, 1.5),
        paint,
      );
      canvas.drawLine(
        center.translate(-2, -11),
        center.translate(-2, -7),
        paint,
      );
      canvas.drawLine(center.translate(2, -9), center.translate(2, -7), paint);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _CoinsIconPainter oldDelegate) =>
      oldDelegate.color != color;
}
