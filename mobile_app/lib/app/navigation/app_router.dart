import 'package:flutter/material.dart';

import '../../features/example/presentation/example_screen.dart';

abstract final class AppRouter {
  static Future<void> openExample(BuildContext context, int number) {
    return Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        settings: RouteSettings(name: '/example/$number'),
        builder: (_) => ExampleScreen(number: number),
      ),
    );
  }
}
