String calendarDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
DateTime weekStart(DateTime date) =>
    DateTime(date.year, date.month, date.day - date.weekday + 1);
DateTime shiftDays(DateTime date, int days) =>
    DateTime(date.year, date.month, date.day + days);

const operationTypes = {
  'expense': 'Расход',
  'income': 'Доход',
  'investment': 'Накопление',
};
const expenseCategories = <String>[
  'Супермаркеты',
  'Фастфуд',
  'Рестораны',
  'Кофейни',
  'Доставка еды',
  'Общественный транспорт',
  'Здоровье и медицина',
  'Аптеки',
  'Красота и уход',
  'Спорт и фитнес',
  'Развлечения',
  'Кино',
  'Книги',
  'Образование',
  'Одежда и обувь',
  'Аксессуары и украшения',
  'Электроника и бытовая техника',
  'Товары для дома',
  'Детские товары',
  'Зоотовары',
  'Цветы',
  'Подарки и сувениры',
  'Подписки и цифровые сервисы',
  'Благотворительность',
  'Прочее',
];

class DiaryEvent {
  DiaryEvent.fromJson(Map<String, dynamic> json)
    : name = json['name'] as String,
      type = json['operation_type'] as String,
      amount = json['amount'] as int,
      category = json['category'] as String?;
  final String name, type;
  final int amount;
  final String? category;
}

class DiaryDay {
  DiaryDay.fromJson(Map<String, dynamic> json)
    : date = DateTime.parse(json['date'] as String),
      events = (json['operations'] as List)
          .map((e) => DiaryEvent.fromJson(e as Map<String, dynamic>))
          .toList();
  final DateTime date;
  final List<DiaryEvent> events;
}

class DiaryWeek {
  DiaryWeek.fromJson(Map<String, dynamic> json)
    : days = (json['days'] as List)
          .map((d) => DiaryDay.fromJson(d as Map<String, dynamic>))
          .toList();
  final List<DiaryDay> days;
}
