import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/features/diary/presentation/diary_screen.dart';
import 'package:frontend/logic/api/api.dart';
import 'package:frontend/logic/diary/diary.dart';
import 'package:frontend/logic/profile/profile_store.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class Store implements ProfileStore {
  @override
  Future<LocalProfile?> read() async =>
      const LocalProfile(username: 'alice', age: 20);
  @override
  Future<void> save(LocalProfile profile) async {}
}

void main() {
  test('week navigation crosses month and year boundaries', () {
    expect(calendarDate(weekStart(DateTime(2027, 1, 1))), '2026-12-28');
    expect(calendarDate(shiftDays(DateTime(2026, 12, 28), 7)), '2027-01-04');
    expect(expenseCategories.length, 25);
  });

  testWidgets(
    'diary signs in, switches weeks and saves expense with category',
    (tester) async {
      final anchors = <String>[];
      Map<String, dynamic>? saved;
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path == '/auth/signin') {
            expect(jsonDecode(request.body), {'username': 'alice'});
            return http.Response('{"access_token":"access"}', 200);
          }
          if (request.url.path == '/api/v1/users/me') {
            expect(request.headers['Authorization'], 'Bearer access');
            return http.Response('{"uuid":"user-id"}', 200);
          }
          expect(request.url.queryParameters['user_uuid'], 'user-id');
          if (request.method == 'POST') {
            saved = jsonDecode(request.body) as Map<String, dynamic>;
            return http.Response('{}', 201);
          }
          final anchor = request.url.queryParameters['anchor_date']!;
          anchors.add(anchor);
          final start = weekStart(DateTime.parse(anchor));
          return http.Response(
            jsonEncode({
              'days': [
                for (var i = 0; i < 7; i++)
                  {
                    'date': calendarDate(shiftDays(start, i)),
                    'operations': [
                      if (saved != null &&
                          saved!['operation_date'] ==
                              calendarDate(shiftDays(start, i)))
                        saved,
                    ],
                  },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(
          home: DiaryScreen(api: api, store: Store()),
        ),
      );
      await tester.pumpAndSettle();
      expect(anchors.length, 1);
      await tester.tap(find.byTooltip('Следующая неделя'));
      await tester.pumpAndSettle();
      expect(
        anchors.last,
        calendarDate(shiftDays(DateTime.parse(anchors.first), 7)),
      );
      await tester.tap(find.text('Добавить событие'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Название'),
        'Продукты',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Сумма, ₽'),
        '450',
      );
      await tester.ensureVisible(find.text('Сохранить событие'));
      await tester.tap(find.text('Сохранить событие'));
      await tester.pumpAndSettle();
      expect(saved, {
        'name': 'Продукты',
        'operation_date': anchors.last,
        'operation_type': 'expense',
        'amount': 450,
        'category': 'Супермаркеты',
      });
      expect(find.text('Продукты'), findsOneWidget);
      expect(find.text('Новое событие'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
