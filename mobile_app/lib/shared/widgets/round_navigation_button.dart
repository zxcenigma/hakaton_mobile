import 'package:flutter/material.dart';

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
    final colors = Theme.of(context).colorScheme;
    final background = switch (number) {
      1 => colors.primaryContainer,
      2 => colors.secondaryContainer,
      3 => colors.tertiaryContainer,
      _ => colors.primary,
    };
    return Semantics(
      label: 'Открыть страницу $number',
      child: SizedBox.square(
        dimension: diameter,
        child: FilledButton(
          onPressed: onPressed,
          style: FilledButton.styleFrom(
            backgroundColor: background,
            foregroundColor: number == 4
                ? colors.onPrimary
                : colors.onPrimaryContainer,
          ),
          child: ExcludeSemantics(child: Text('$number')),
        ),
      ),
    );
  }
}
