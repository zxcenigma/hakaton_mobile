import 'package:flutter/material.dart';

import '../features/home/presentation/home_screen.dart';
import 'theme/app_theme.dart';

class PetApp extends StatelessWidget {
  const PetApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Лавандовый котик',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      home: const HomeScreen(),
    );
  }
}
