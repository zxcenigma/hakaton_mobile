import 'package:flutter/material.dart';
import '../../../../app/theme/app_theme.dart';

/// A quiet, warm charcoal backdrop with diffuse overhead light.
class StageBackground extends StatelessWidget {
  const StageBackground({super.key});

  @override
  Widget build(BuildContext context) => const IgnorePointer(
    child: ExcludeSemantics(
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.35),
            radius: 1.15,
            colors: [AppPalette.stageLight, AppPalette.stageBackground],
            stops: [0, 1],
          ),
        ),
      ),
    ),
  );
}
