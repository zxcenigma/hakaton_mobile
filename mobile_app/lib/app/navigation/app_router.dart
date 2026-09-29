import 'package:flutter/material.dart';

import '../../features/diary/presentation/diary_screen.dart';

import '../../features/example/presentation/example_screen.dart';

abstract final class AppRouter {
  static Future<void> openExample(BuildContext context, int number) {
    return Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        settings: RouteSettings(
          name: number == 4 ? '/diary' : '/example/$number',
        ),
        builder: (_) =>
            number == 4 ? const DiaryScreen() : ExampleScreen(number: number),
      ),
    );
  }
}
