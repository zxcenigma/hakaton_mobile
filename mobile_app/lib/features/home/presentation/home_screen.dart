import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/navigation/app_router.dart';
import '../../../shared/widgets/round_navigation_button.dart';
import 'widgets/pet_illustration.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final inset = constraints.maxWidth < 360 ? 16.0 : 24.0;
            final available = constraints.maxWidth - inset * 2;
            final diameter = ((available - 48) / 4).clamp(48.0, 64.0);
            // Preserve room for accessible buttons at large text sizes.
            final textHeight = MediaQuery.textScalerOf(context).scale(18);
            final buttonSize = math.max(diameter, textHeight + 16);
            final rowWidth = math.max(available, buttonSize * 4 + 48);

            return Column(
              children: [
                const Expanded(
                  child: Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: PetIllustration(),
                    ),
                  ),
                ),
                Padding(
                  padding: EdgeInsets.fromLTRB(inset, 12, inset, 20),
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SizedBox(
                      width: rowWidth,
                      child: Row(
                        children: [
                          for (final number in [1, 2]) ...[
                            RoundNavigationButton(
                              number: number,
                              diameter: buttonSize,
                              onPressed: () =>
                                  AppRouter.openExample(context, number),
                            ),
                            if (number == 1) const SizedBox(width: 8),
                          ],
                          const Spacer(),
                          for (final number in [3, 4]) ...[
                            if (number == 4) const SizedBox(width: 8),
                            RoundNavigationButton(
                              number: number,
                              diameter: buttonSize,
                              onPressed: () =>
                                  AppRouter.openExample(context, number),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
