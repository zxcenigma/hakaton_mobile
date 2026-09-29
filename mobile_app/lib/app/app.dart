import 'package:flutter/material.dart';

import '../features/home/presentation/home_screen.dart';
import 'theme/app_theme.dart';
import '../features/startup/presentation/startup_screen.dart';
import '../logic/api/api.dart';
import '../logic/profile/profile_store.dart';

class PetApp extends StatelessWidget {
  const PetApp({super.key, this.api, this.profileStore, this.home});

  final ApiService? api;
  final ProfileStore? profileStore;
  final Widget? home;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Киса Копилка',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      home:
          home ??
          StartupScreen(
            api: api,
            store: profileStore,
            home: const HomeScreen(),
          ),
    );
  }
}
