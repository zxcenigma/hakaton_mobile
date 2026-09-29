abstract final class AppSections {
  static String title(int number) => switch (number) {
    1 => 'Цели',
    2 => 'Советник',
    3 => 'Магазин',
    4 => 'Дневник',
    _ => throw ArgumentError.value(number, 'number', 'Неизвестный раздел'),
  };
}
