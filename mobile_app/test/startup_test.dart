import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/app/theme/app_theme.dart';
import 'package:frontend/features/startup/presentation/startup_screen.dart';
import 'package:frontend/features/startup/presentation/widgets/name_dialog.dart';
import 'package:frontend/features/startup/presentation/widgets/chasing_cat.dart';
import 'package:frontend/logic/api/api.dart';
import 'package:frontend/logic/profile/profile_store.dart';

class FakeApi extends ApiService {
  Future<void> Function()? health;
  Future<void> Function()? register;
  int signups = 0;
  LocalProfile? submitted;

  @override
  Future<void> checkReady() async => health?.call();

  @override
  Future<void> signup({required String username, required int age}) async {
    signups++;
    submitted = LocalProfile(username: username, age: age);
    await register?.call();
  }
}

class MemoryStore implements ProfileStore {
  LocalProfile? profile;
  bool failSave = false;
  @override
  Future<LocalProfile?> read() async => profile;
  @override
  Future<void> save(LocalProfile value) async {
    if (failSave) throw StateError('storage unavailable');
    profile = value;
  }
}

Future<void> advance(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
}

Future<void> launch(WidgetTester tester, FakeApi api, MemoryStore store) async {
  // Decode real bundled artwork before entering fake async widget time.
  await tester.pumpWidget(const MaterialApp(home: SizedBox()));
  final context = tester.element(find.byType(SizedBox).first);
  await tester.runAsync(() async {
    for (final path in [
      'assets/image/logo.png',
      'assets/image/loading_page.png',
    ]) {
      await precacheImage(AssetImage(path), context);
    }
  });
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      home: StartupScreen(
        api: api,
        store: store,
        home: const Scaffold(body: Text('Главный экран')),
      ),
    ),
  );
}

void main() {
  testWidgets('waits for API then submits name and slider age once', (
    tester,
  ) async {
    final health = Completer<void>();
    final signup = Completer<void>();
    final api = FakeApi()
      ..health = (() => health.future)
      ..register = (() => signup.future);
    addTearDown(api.close);
    final store = MemoryStore();
    await launch(tester, api, store);
    expect(find.byKey(const ValueKey('startup-logo')), findsOneWidget);
    await advance(tester);
    expect(find.byType(NameDialog), findsNothing);
    expect(find.text('Главный экран'), findsNothing);
    health.complete();
    await advance(tester);
    expect(find.byType(NameDialog), findsOneWidget);
    await tester.enterText(find.byType(TextFormField), ' Саша ');
    await tester.ensureVisible(find.byType(Slider));
    await tester.drag(find.byType(Slider), const Offset(50, 0));
    await tester.pump();
    final age = tester.widget<Slider>(find.byType(Slider)).value.round();
    expect(age, isNot(18));
    await tester.ensureVisible(find.text('Начать копить'));
    await tester.tap(find.text('Начать копить'));
    await tester.pump();
    expect(api.signups, 1);
    expect(api.submitted!.username, 'Саша');
    expect(api.submitted!.age, age);
    expect(store.profile, isNull);
    expect(find.text('Главный экран'), findsNothing);
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNull,
    );
    signup.complete();
    await advance(tester);
    expect(store.profile!.age, age);
    expect(find.text('Главный экран'), findsOneWidget);
    expect(find.byType(NameDialog), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('returning user skips signup after successful health check', (
    tester,
  ) async {
    final api = FakeApi();
    addTearDown(api.close);
    final store = MemoryStore()
      ..profile = const LocalProfile(username: 'Саша', age: 18);
    await launch(tester, api, store);
    await advance(tester);
    expect(find.text('Главный экран'), findsOneWidget);
    expect(find.byType(NameDialog), findsNothing);
    expect(api.signups, 0);
  });

  testWidgets('offline startup retries without exposing home early', (
    tester,
  ) async {
    final api = FakeApi()
      ..health = (() async => throw const ApiException('Нет связи'));
    addTearDown(api.close);
    final store = MemoryStore()
      ..profile = const LocalProfile(username: 'Саша', age: 18);
    await launch(tester, api, store);
    await advance(tester);
    expect(find.text('Нет связи'), findsOneWidget);
    expect(find.text('Главный экран'), findsNothing);
    api.health = null;
    await tester.ensureVisible(find.text('Попробовать ещё раз'));
    await tester.tap(find.text('Попробовать ещё раз'));
    await advance(tester);
    expect(find.text('Главный экран'), findsOneWidget);
  });

  testWidgets(
    'signup failure preserves fields; failed local save does not repeat signup',
    (tester) async {
      final api = FakeApi()
        ..register = (() async =>
            throw const ApiException('Не удалось зарегистрировать'));
      addTearDown(api.close);
      final store = MemoryStore();
      await launch(tester, api, store);
      await advance(tester);
      await tester.enterText(find.byType(TextFormField), 'Лев');
      await tester.ensureVisible(find.text('Начать копить'));
      await tester.tap(find.text('Начать копить'));
      await tester.pump();
      expect(find.text('Не удалось зарегистрировать'), findsOneWidget);
      expect(store.profile, isNull);
      expect(find.text('Лев'), findsOneWidget);
      api.register = null;
      store.failSave = true;
      await tester.ensureVisible(find.text('Начать копить'));
      await tester.tap(find.text('Начать копить'));
      await tester.pump();
      expect(api.signups, 2);
      store.failSave = false;
      await tester.ensureVisible(find.text('Начать копить'));
      await tester.tap(find.text('Начать копить'));
      await advance(tester);
      expect(api.signups, 2);
      expect(store.profile!.username, 'Лев');
      expect(find.text('Главный экран'), findsOneWidget);
    },
  );

  testWidgets(
    'small keyboard viewport supports empty-name validation and age slider',
    (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = FakeApi();
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.dark,
          home: MediaQuery(
            data: const MediaQueryData(
              size: Size(320, 480),
              textScaler: TextScaler.linear(1.6),
              viewInsets: EdgeInsets.only(bottom: 180),
            ),
            child: Scaffold(
              body: NameDialog(api: api, store: MemoryStore()),
            ),
          ),
        ),
      );
      await tester.ensureVisible(find.text('Начать копить'));
      await tester.tap(find.text('Начать копить'));
      await tester.pump();
      expect(find.text('Введите имя'), findsOneWidget);
      expect(api.signups, 0);
      await tester.ensureVisible(find.byType(Slider));
      await tester.drag(find.byType(Slider), const Offset(50, 0));
      await tester.pump();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('cat animation respects reduced motion and disposes cleanly', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: true),
          child: ChasingCat(),
        ),
      ),
    );
    await tester.pump();
    expect(tester.binding.hasScheduledFrame, isFalse);
    await tester.pumpWidget(const MaterialApp(home: ChasingCat()));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.binding.hasScheduledFrame, isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(tester.binding.hasScheduledFrame, isFalse);
  });
}
