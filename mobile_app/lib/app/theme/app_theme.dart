import 'package:flutter/material.dart';

abstract final class AppPalette {
  static const background = Color(0xFFF7F3FC);
  static const surface = Color(0xFFFFFBFF);
  static const purple = Color(0xFF7861A8);
  static const lavender = Color(0xFFE8DFF5);
  static const pink = Color(0xFFF0DDE8);
  static const mint = Color(0xFFDDECE5);
  static const ink = Color(0xFF30283E);
  static const muted = Color(0xFF70677D);
  static const pet = Color(0xFFCCBCE5);
  static const petShade = Color(0xFFB5A0D3);
}

abstract final class AppTheme {
  static final light = ThemeData(
    useMaterial3: true,
    colorScheme:
        ColorScheme.fromSeed(
          seedColor: AppPalette.purple,
          brightness: Brightness.light,
        ).copyWith(
          primary: AppPalette.purple,
          onPrimary: AppPalette.surface,
          primaryContainer: AppPalette.lavender,
          onPrimaryContainer: AppPalette.ink,
          secondaryContainer: AppPalette.pink,
          onSecondaryContainer: AppPalette.ink,
          tertiaryContainer: AppPalette.mint,
          onTertiaryContainer: AppPalette.ink,
          surface: AppPalette.surface,
          onSurface: AppPalette.ink,
          onSurfaceVariant: AppPalette.muted,
        ),
    scaffoldBackgroundColor: AppPalette.background,
    textTheme: const TextTheme(
      headlineSmall: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
      titleLarge: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
      bodyLarge: TextStyle(fontSize: 17, height: 1.5),
    ).apply(bodyColor: AppPalette.ink, displayColor: AppPalette.ink),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: const CircleBorder(),
        padding: EdgeInsets.zero,
        textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
  );
}
