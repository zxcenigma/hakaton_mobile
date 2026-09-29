import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/logic/api/api.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('signup sends only trimmed username and integer age', () async {
    final api = ApiService(
      client: MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.toString(), 'http://91.210.106.86:6767/auth/signup');
        expect(request.headers['content-type'], contains('application/json'));
        expect(jsonDecode(request.body), {'username': 'Саша', 'age': 23});
        return http.Response('{}', 201);
      }),
    );
    addTearDown(api.close);
    await api.signup(username: ' Саша ', age: 23);
  });

  test('root 200 is enough; 404 uses an actual signup schema', () async {
    for (final rootStatus in [200, 404]) {
      final paths = <String>[];
      final api = ApiService(
        client: MockClient((request) async {
          paths.add(request.url.path);
          if (request.url.path == '/') return http.Response('', rootStatus);
          return http.Response('{"paths":{"/auth/signup":{}}}', 200);
        }),
      );
      await api.checkReady();
      expect(paths, rootStatus == 200 ? ['/'] : ['/', '/openapi.json']);
      api.close();
    }
  });

  test('health does not accept HTML or hide server errors', () async {
    for (final rootStatus in [404, 500]) {
      final api = ApiService(
        client: MockClient(
          (request) async => http.Response(
            request.url.path == '/' ? '' : '<html>Proxy</html>',
            request.url.path == '/' ? rootStatus : 200,
          ),
        ),
      );
      await expectLater(api.checkReady(), throwsA(isA<ApiException>()));
      api.close();
    }
  });

  test('signup propagates validation and conflict failures', () async {
    for (final status in [409, 422, 500]) {
      final api = ApiService(
        client: MockClient((_) async => http.Response('{}', status)),
      );
      await expectLater(
        api.signup(username: 'Саша', age: 18),
        throwsA(isA<ApiException>()),
      );
      api.close();
    }
  });

  test('old email/password contract gets a readable error', () async {
    final api = ApiService(
      client: MockClient(
        (_) async => http.Response(
          '{"detail":[{"loc":["body","email"],"type":"missing"}]}',
          422,
        ),
      ),
    );
    addTearDown(api.close);
    await expectLater(
      api.signup(username: 'Саша', age: 18),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          contains('после обновления сервера'),
        ),
      ),
    );
  });

  test('network errors and timeout are retryable API errors', () async {
    final clients = [
      MockClient((_) async => throw http.ClientException('offline')),
      MockClient((_) => Completer<http.Response>().future),
    ];
    for (final client in clients) {
      final api = ApiService(
        client: client,
        timeout: const Duration(milliseconds: 10),
      );
      await expectLater(api.checkReady(), throwsA(isA<ApiException>()));
      api.close();
    }
  });
}
