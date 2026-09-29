import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../diary/diary.dart';

const String baseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://91.210.106.86:6767',
);

class ApiException implements Exception {
  const ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class ApiService {
  ApiService({
    http.Client? client,
    String url = baseUrl,
    this.timeout = const Duration(seconds: 15),
  }) : _client = client ?? http.Client(),
       _base = Uri.parse(url);

  final http.Client _client;
  final Uri _base;
  final Duration timeout;

  Future<http.Response> _send(
    String path, {
    Map<String, Object>? body,
    Map<String, String>? query,
    String? token,
  }) async {
    final uri = _base.resolve(path).replace(queryParameters: query);
    final headers = <String, String>{
      "accept": "application/json",
      if (token != null) "Authorization": "Bearer $token",
    };
    try {
      return await (body == null
              ? _client.get(uri, headers: headers)
              : _client.post(
                  uri,
                  headers: {
                    ...headers,
                    'Content-Type': 'application/json; charset=utf-8',
                  },
                  body: jsonEncode(body),
                ))
          .timeout(timeout);
    } on TimeoutException {
      throw const ApiException('Сервер долго не отвечает. Попробуйте ещё раз.');
    } on http.ClientException {
      throw const ApiException(
        'Не удалось подключиться. Проверьте интернет и попробуйте ещё раз.',
      );
    }
  }

  Future<void> checkReady() async {
    final response = await _send('/');
    if (response.statusCode == 200) return;
    // The current deployment has no root health endpoint yet.
    if (response.statusCode == 404) {
      final schema = await _send('/openapi.json');
      if (schema.statusCode == 200) {
        try {
          final data = jsonDecode(utf8.decode(schema.bodyBytes));
          if (data is Map &&
              data['paths'] is Map &&
              (data['paths'] as Map).containsKey('/auth/signup')) {
            return;
          }
        } on FormatException {
          // A proxy's HTML page is not a successful API health check.
        }
      }
    }
    throw const ApiException(
      'Копилка пока не может связаться с сервером. Попробуйте ещё раз чуть позже.',
    );
  }

  Future<void> signup({required String username, required int age}) async {
    final response = await _send(
      '/auth/signup',
      body: {'username': username.trim(), 'age': age},
    );
    if (response.statusCode == 200 || response.statusCode == 201) return;
    if (response.statusCode == 409) {
      throw const ApiException('Это имя уже занято. Попробуйте другое.');
    }
    if (response.statusCode == 422) {
      // Explain the deployed contract mismatch without asking for invented credentials.
      try {
        final data = jsonDecode(utf8.decode(response.bodyBytes));
        final details = data is Map ? data['detail'] : null;
        if (details is List &&
            details.any(
              (entry) =>
                  entry is Map &&
                  entry['loc'] is List &&
                  (entry['loc'] as List).any(
                    (field) => field == 'email' || field == 'password',
                  ),
            )) {
          throw const ApiException(
            'Регистрация по имени пока недоступна. Попробуйте после обновления сервера.',
          );
        }
      } on FormatException {
        // Fall back to a readable validation error.
      }
      throw const ApiException(
        'Сервер не принял данные. Проверьте имя и возраст и попробуйте ещё раз.',
      );
    }
    throw const ApiException(
      'Не получилось сохранить имя. Попробуйте ещё раз.',
    );
  }

  Map<String, dynamic> _object(http.Response response) {
    try {
      final value = jsonDecode(utf8.decode(response.bodyBytes));
      if (value is Map<String, dynamic>) return value;
    } on FormatException {
      // Report an invalid server response through the same retry UI.
    }
    throw const ApiException(
      'Сервер вернул некорректный ответ. Попробуйте ещё раз.',
    );
  }

  void _requireSuccess(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw const ApiException(
        'Не удалось войти. Проверьте, что ваш профиль доступен на сервере.',
      );
    }
    if (response.statusCode == 404) {
      throw const ApiException('Профиль или дневник не найден на сервере.');
    }
    if (response.statusCode == 422) {
      throw const ApiException('Проверьте дату, название и сумму события.');
    }
    throw const ApiException(
      'Не удалось выполнить запрос. Попробуйте ещё раз.',
    );
  }

  Future<String> diaryUser(String username) async {
    final login = await _send('/auth/signin', body: {'username': username});
    _requireSuccess(login);
    final token = _object(login)['access_token'];
    if (token is! String || token.isEmpty) {
      throw const ApiException('Сервер не вернул токен входа.');
    }
    final me = await _send('/api/v1/users/me', token: token);
    _requireSuccess(me);
    final uuid = _object(me)['uuid'];
    if (uuid is! String || uuid.isEmpty) {
      throw const ApiException('Сервер не вернул идентификатор профиля.');
    }
    return uuid;
  }

  Future<DiaryWeek> diaryWeek(String userUuid, DateTime anchor) async {
    final response = await _send(
      '/api/v1/diary/week',
      query: {'user_uuid': userUuid, 'anchor_date': calendarDate(anchor)},
    );
    _requireSuccess(response);
    try {
      return DiaryWeek.fromJson(_object(response));
    } on FormatException {
      throw const ApiException('Не удалось прочитать дневник с сервера.');
    } on TypeError {
      throw const ApiException('Не удалось прочитать дневник с сервера.');
    }
  }

  Future<void> addDiaryEvent(String userUuid, Map<String, Object> event) async {
    final response = await _send(
      '/api/v1/diary/operations',
      query: {'user_uuid': userUuid},
      body: event,
    );
    _requireSuccess(response);
  }

  void close() => _client.close();
}
