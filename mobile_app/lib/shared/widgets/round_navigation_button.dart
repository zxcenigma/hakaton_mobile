import 'package:flutter/material.dart';
import '../../app/theme/app_theme.dart';
import '../../app/navigation/app_sections.dart';

class RoundNavigationButton extends StatelessWidget {
  const RoundNavigationButton({
    required this.number,
    required this.onPressed,
    this.diameter = 60,
    super.key,
  });

  final int number;
  final VoidCallback onPressed;
  final double diameter;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Открыть страницу $number',
      hint: AppSections.title(number),
      child: SizedBox.square(
        dimension: diameter,
        child: FilledButton(
          onPressed: onPressed,
          style: FilledButton.styleFrom(
            backgroundColor: AppPalette.darkGold,
            foregroundColor: AppPalette.gold,
            elevation: 3,
            shadowColor: AppPalette.ink.withValues(alpha: 0.22),
            side: BorderSide(color: AppPalette.gold.withValues(alpha: 0.45)),
          ),
          child: ExcludeSemantics(
            child: Icon(switch (number) {
              1 => Icons.track_changes_rounded,
              2 => Icons.lightbulb_outline_rounded,
              3 => Icons.storefront_rounded,
              _ => Icons.pets_rounded,
            }, size: 28),
          ),
        ),
      ),
    );
  }
}
