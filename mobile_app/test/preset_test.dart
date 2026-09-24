import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/app/app.dart';
import 'package:frontend/features/home/presentation/widgets/pet_illustration.dart';
import 'package:frontend/shared/widgets/oval_app_bar.dart';
import 'package:frontend/shared/widgets/round_navigation_button.dart';

// A living character continuously schedules frames: wait for route transitions,
// not for all animations in the application to become idle.
Future<void> pumpTransition(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
  await tester.pump();
}

void main() {
  testWidgets('Pet reacts to touch and disposes running animations', (
    tester,
  ) async {
    await tester.pumpWidget(const PetApp());
    await tester.pump(const Duration(seconds: 1));
    expect(tester.binding.hasScheduledFrame, isTrue);
    await tester.tap(find.byType(PetIllustration));
    await tester.pump(const Duration(milliseconds: 200));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(tester.binding.hasScheduledFrame, isFalse);
  });

  testWidgets('Reduced motion leaves the pet still, including after touch', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: true),
          child: Center(child: PetIllustration()),
        ),
      ),
    );
    await tester.pump();
    expect(tester.binding.hasScheduledFrame, isFalse);
    await tester.tap(find.byType(PetIllustration));
    await tester.pump();
    expect(tester.binding.hasScheduledFrame, isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Four corner buttons open their page and return home', (
    tester,
  ) async {
    await tester.pumpWidget(const PetApp());
    expect(find.byType(PetIllustration), findsOneWidget);
    expect(find.byType(RoundNavigationButton), findsNWidgets(4));
    expect(find.byType(BottomNavigationBar), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);

    final positions = [
      for (var n = 1; n <= 4; n++) tester.getCenter(find.text('$n')),
    ];
    expect(
      positions[1].dx - positions[0].dx,
      lessThan(positions[2].dx - positions[1].dx),
    );
    expect(positions.every((point) => point.dy == positions.first.dy), isTrue);

    for (var number = 1; number <= 4; number++) {
      await tester.tap(find.text('$number'));
      await pumpTransition(tester);
      expect(find.text('Example $number'), findsOneWidget);
      expect(
        find.text('Страница $number — здесь появится содержимое'),
        findsOneWidget,
      );
      final material = tester.widget<Material>(
        find
            .descendant(
              of: find.byType(OvalAppBar),
              matching: find.byType(Material),
            )
            .first,
      );
      expect(material.shape, isA<StadiumBorder>());
      if (number.isOdd) {
        await tester.tap(find.byTooltip('Назад'));
      } else {
        await tester.binding.handlePopRoute();
      }
      await pumpTransition(tester);
      expect(find.byType(PetIllustration), findsOneWidget);
      expect(tester.takeException(), isNull);
    }
  });

  for (final size in [const Size(320, 480), const Size(568, 320)]) {
    testWidgets('Small viewport $size with enlarged text and safe insets', (
      tester,
    ) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: MediaQueryData(
              size: size,
              textScaler: TextScaler.linear(2),
              padding: const EdgeInsets.only(top: 24, bottom: 34),
            ),
            child: const PetApp(),
          ),
        ),
      );
      await pumpTransition(tester);
      expect(tester.takeException(), isNull);
      for (var number = 1; number <= 4; number++) {
        final button = find.widgetWithText(FilledButton, '$number');
        final rect = tester.getRect(button);
        expect(rect.width, greaterThanOrEqualTo(48));
        expect(rect.height, greaterThanOrEqualTo(48));
        expect(rect.bottom, lessThanOrEqualTo(size.height - 34));
        await tester.tap(button);
        await pumpTransition(tester);
        expect(find.text('Example $number'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.tap(find.byTooltip('Назад'));
        await pumpTransition(tester);
      }
    });
  }

  testWidgets('Buttons expose their destination to screen readers', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    try {
      await tester.pumpWidget(const PetApp());
      for (var n = 1; n <= 4; n++) {
        expect(find.bySemanticsLabel('Открыть страницу $n'), findsOneWidget);
      }
    } finally {
      semantics.dispose();
    }
  });
}
