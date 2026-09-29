import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class LocalProfile {
  const LocalProfile({required this.username, required this.age});
  final String username;
  final int age;

  Map<String, Object> toJson() => {'username': username, 'age': age};
}

abstract interface class ProfileStore {
  Future<LocalProfile?> read();
  Future<void> save(LocalProfile profile);
}

/// Local onboarding data, not an authentication token or server session.
class LocalProfileStore implements ProfileStore {
  static const _key = 'onboarding.profile.v1';

  @override
  Future<LocalProfile?> read() async {
    final value = await SharedPreferencesAsync().getString(_key);
    if (value == null) return null;
    try {
      final data = jsonDecode(value);
      if (data is! Map || data['username'] is! String || data['age'] is! int) {
        return null;
      }
      final name = (data['username'] as String).trim();
      final age = data['age'] as int;
      if (name.isEmpty || age < 1 || age > 100) return null;
      return LocalProfile(username: name, age: age);
    } on FormatException {
      return null;
    }
  }

  @override
  Future<void> save(LocalProfile profile) =>
      SharedPreferencesAsync().setString(_key, jsonEncode(profile.toJson()));
}
