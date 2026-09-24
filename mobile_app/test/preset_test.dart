import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/app/app.dart';
import 'package:frontend/app/navigation/app_sections.dart';
import 'package:frontend/features/home/presentation/widgets/pet_illustration.dart';
import 'package:frontend/features/home/presentation/widgets/pet_skin.dart';
import 'package:frontend/features/home/presentation/home_screen.dart';
import 'package:frontend/shared/widgets/oval_app_bar.dart';
import 'package:frontend/shared/widgets/round_navigation_button.dart';

// A living character continuously schedules frames: wait for route transitions,
// not for all animations in the application to become idle.
Future<void> pumpTransition(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
  await tester.pump();
}

Finder navigationButton(int number) => find.byWidgetPredicate(
  (widget) => widget is RoundNavigationButton && widget.number == number,
);

void main() {
  testWidgets('Podium stays fixed while the cat reacts', (tester) async {
    await tester.pumpWidget(const PetApp());
    final podium = find.byKey(const ValueKey('pet-podium'));
    final position = tester.getRect(podium);
    final boundary = tester.renderObject<RenderRepaintBoundary>(podium);
    Future<List<int>?> snapshot() => tester.runAsync(() async {
      final image = await boundary.toImage();
      try {
        final bytes = await image.toByteData();
        return bytes!.buffer.asUint8List().toList();
      } finally {
        image.dispose();
      }
    });
    final before = await snapshot();
    await tester.tap(find.byType(PetIllustration));
    await tester.pump(const Duration(milliseconds: 200));
    final after = await snapshot();
    expect(tester.getRect(podium), position);
    expect(after, orderedEquals(before!));
  });

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
      for (var n = 1; n <= 4; n++) tester.getCenter(navigationButton(n)),
    ];
    expect(positions[0].dx, positions[1].dx);
    expect(positions[2].dx, positions[3].dx);
    expect(positions[0].dy, positions[2].dy);
    expect(positions[1].dy, positions[3].dy);
    expect(positions[0].dy, lessThan(positions[1].dy));
    expect(positions[0].dx, lessThan(positions[2].dx));

    for (var number = 1; number <= 4; number++) {
      await tester.tap(navigationButton(number));
      await pumpTransition(tester);
      expect(find.text(AppSections.title(number)), findsOneWidget);
      expect(
        find.text('${AppSections.title(number)} — здесь появится содержимое'),
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
            child: const HomeScreen(),
          ),
        ),
      );
      await pumpTransition(tester);
      expect(tester.takeException(), isNull);
      for (var number = 1; number <= 4; number++) {
        final button = navigationButton(number);
        await tester.ensureVisible(button);
        await tester.pump();
        final rect = tester.getRect(button);
        expect(rect.width, greaterThanOrEqualTo(48));
        expect(rect.height, greaterThanOrEqualTo(48));
        expect(rect.bottom, lessThanOrEqualTo(size.height - 34));
        await tester.tap(button);
        await pumpTransition(tester);
        expect(find.text(AppSections.title(number)), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.tap(find.byTooltip('Назад'));
        await pumpTransition(tester);
      }
    });
  }

  testWidgets('Selecting a skin closes the wardrobe and survives navigation', (
    tester,
  ) async {
    await tester.pumpWidget(const PetApp());
    for (final skin in PetSkin.values) {
      await tester.tap(find.byTooltip('Гардероб'));
      await pumpTransition(tester);
      final tile = find.widgetWithText(ListTile, skin.label);
      await tester.ensureVisible(tile);
      await tester.tap(tile);
      await pumpTransition(tester);
      expect(find.byType(ListTile), findsNothing);
      expect(
        tester.widget<PetIllustration>(find.byType(PetIllustration)).skin,
        skin,
      );
      await tester.tap(navigationButton(1));
      await pumpTransition(tester);
      await tester.tap(find.byTooltip('Назад'));
      await pumpTransition(tester);
      expect(
        tester.widget<PetIllustration>(find.byType(PetIllustration)).skin,
        skin,
      );
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('Entire home respects reduced motion', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: true),
          child: HomeScreen(),
        ),
      ),
    );
    await tester.pump();
    expect(tester.binding.hasScheduledFrame, isFalse);
    await tester.tap(find.byType(PetIllustration));
    await tester.pump();
    expect(tester.binding.hasScheduledFrame, isFalse);
  });

  testWidgets('Deposit validates, animates, and adds each amount only once', (
    tester,
  ) async {
    await tester.pumpWidget(const PetApp());
    expect(find.text('Баланс · 0 ₽'), findsOneWidget);
    await tester.ensureVisible(find.byTooltip('Пополнить копилку'));
    await tester.tap(find.byTooltip('Пополнить копилку'));
    await pumpTransition(tester);
    await pumpTransition(tester);
    await tester.enterText(find.byType(TextFormField), '0');
    await tester.tap(find.text('Положить в копилку'));
    await tester.pump();
    expect(find.text('Введите от 1 до 1 000 000 ₽'), findsOneWidget);
    await tester.enterText(find.byType(TextFormField), '500');
    await tester.tap(find.text('Положить в копилку'));
    await pumpTransition(tester);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Баланс · 500 ₽'), findsOneWidget);
    expect(find.text('+500 ₽'), findsOneWidget);
    await tester.tap(navigationButton(1));
    await pumpTransition(tester);
    await tester.tap(find.byTooltip('Назад'));
    await pumpTransition(tester);
    expect(find.text('Баланс · 500 ₽'), findsOneWidget);
    // Dismissing a second deposit must not alter the balance.
    await tester.ensureVisible(find.byTooltip('Пополнить копилку'));
    await tester.tap(find.byTooltip('Пополнить копилку'));
    await pumpTransition(tester);
    await pumpTransition(tester);
    await tester.binding.handlePopRoute();
    await pumpTransition(tester);
    expect(find.text('Баланс · 500 ₽'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'Deposit works with reduced motion and a small keyboard viewport',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(320, 480);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(
        MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              disableAnimations: true,
              viewInsets: const EdgeInsets.only(bottom: 180),
            ),
            child: child!,
          ),
          home: const HomeScreen(),
        ),
      );
      await tester.ensureVisible(find.byTooltip('Пополнить копилку'));
      await tester.tap(find.byTooltip('Пополнить копилку'));
      await pumpTransition(tester);
      await tester.enterText(find.byType(TextFormField), '750');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await pumpTransition(tester);
      expect(find.text('Баланс · 750 ₽'), findsOneWidget);
      expect(find.text('+750 ₽'), findsOneWidget);
      await tester.pump(const Duration(seconds: 5));
      expect(find.text('+750 ₽'), findsOneWidget);
      await tester.pump(const Duration(seconds: 2));
      expect(find.text('+750 ₽'), findsNothing);
      expect(find.text('Баланс · 750 ₽'), findsOneWidget);
      expect(tester.takeException(), isNull);
      expect(tester.binding.hasScheduledFrame, isFalse);
    },
  );

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
