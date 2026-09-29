import 'package:flutter/material.dart';

import '../../../logic/api/api.dart';
import '../../../logic/diary/diary.dart';
import '../../../logic/profile/profile_store.dart';
import '../../../shared/widgets/oval_app_bar.dart';

const _weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
String _dateLabel(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}.${date.month.toString().padLeft(2, '0')}.${date.year}';

class DiaryScreen extends StatefulWidget {
  const DiaryScreen({super.key, this.api, this.store});
  final ApiService? api;
  final ProfileStore? store;
  @override
  State<DiaryScreen> createState() => _DiaryScreenState();
}

class _DiaryScreenState extends State<DiaryScreen> {
  late final ApiService _api = widget.api ?? ApiService();
  DateTime _start = weekStart(DateTime.now());
  DiaryWeek? _week;
  String? _uuid, _error;
  bool _loading = true;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final request = ++_request;
    final anchor = _start;
    setState(() {
      _loading = true;
      _error = null;
      _week = null;
    });
    try {
      if (_uuid == null) {
        final profile = await (widget.store ?? LocalProfileStore()).read();
        if (profile == null) {
          throw const ApiException(
            'Сначала создайте профиль на стартовом экране приложения.',
          );
        }
        _uuid = await _api.diaryUser(profile.username);
      }
      final week = await _api.diaryWeek(_uuid!, anchor);
      if (mounted && request == _request) setState(() => _week = week);
    } catch (error) {
      if (mounted && request == _request) {
        setState(
          () => _error = error is ApiException
              ? error.message
              : 'Не удалось загрузить дневник. Попробуйте ещё раз.',
        );
      }
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  void _move(int days) {
    setState(() => _start = shiftDays(_start, days));
    _load();
  }

  Future<void> _add(DateTime date) async {
    if (_uuid == null) return;
    final savedDate = await showModalBottomSheet<DateTime>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _EventForm(api: _api, uuid: _uuid!, date: date),
    );
    if (!mounted || savedDate == null) return;
    setState(() => _start = weekStart(savedDate));
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Событие добавлено')));
    await _load();
  }

  @override
  void dispose() {
    if (widget.api == null) _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Column(
        children: [
          const OvalAppBar(title: 'Дневник'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
            child: Row(
              children: [
                IconButton(
                  tooltip: 'Предыдущая неделя',
                  onPressed: _loading ? null : () => _move(-7),
                  icon: const Icon(Icons.chevron_left),
                ),
                Expanded(
                  child: Text(
                    '${_dateLabel(_start)} — ${_dateLabel(shiftDays(_start, 6))}',
                    textAlign: TextAlign.center,
                  ),
                ),
                IconButton(
                  tooltip: 'Следующая неделя',
                  onPressed: _loading ? null : () => _move(7),
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: _loading
                ? null
                : () {
                    setState(() => _start = weekStart(DateTime.now()));
                    _load();
                  },
            child: const Text('Текущая неделя'),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                ? SingleChildScrollView(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(_error!, textAlign: TextAlign.center),
                          TextButton(
                            onPressed: _load,
                            child: const Text('Попробовать ещё раз'),
                          ),
                        ],
                      ),
                    ),
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 100),
                      children: [for (final day in _week!.days) _dayCard(day)],
                    ),
                  ),
          ),
        ],
      ),
    ),
    floatingActionButton: _loading || _error != null
        ? null
        : FloatingActionButton.extended(
            onPressed: () {
              final today = DateTime.now();
              _add(
                weekStart(today) == _start
                    ? DateTime(today.year, today.month, today.day)
                    : _start,
              );
            },
            icon: const Icon(Icons.add),
            label: const Text('Добавить событие'),
          ),
  );

  Widget _dayCard(DiaryDay day) => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${_weekdays[day.date.weekday - 1]}, ${_dateLabel(day.date)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              IconButton(
                tooltip: 'Добавить событие ${_dateLabel(day.date)}',
                onPressed: () => _add(day.date),
                icon: const Icon(Icons.add),
              ),
            ],
          ),
          if (day.events.isEmpty)
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text('Пока нет событий'),
            ),
          for (final event in day.events)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    event.type == 'income'
                        ? Icons.south_west
                        : event.type == 'expense'
                        ? Icons.north_east
                        : Icons.savings_outlined,
                    size: 20,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(event.name),
                        Text(
                          event.category ??
                              operationTypes[event.type] ??
                              event.type,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      '${event.type == 'income' ? '+' : '−'}${event.amount} ₽',
                      textAlign: TextAlign.end,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    ),
  );
}

class _EventForm extends StatefulWidget {
  const _EventForm({required this.api, required this.uuid, required this.date});
  final ApiService api;
  final String uuid;
  final DateTime date;
  @override
  State<_EventForm> createState() => _EventFormState();
}

class _EventFormState extends State<_EventForm> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _amount = TextEditingController();
  late DateTime _date = widget.date;
  String _type = 'expense', _category = expenseCategories.first;
  String? _error;
  bool _saving = false;

  Future<void> _save() async {
    if (_saving || !_form.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.addDiaryEvent(widget.uuid, {
        'name': _name.text.trim(),
        'operation_date': calendarDate(_date),
        'operation_type': _type,
        'amount': int.parse(_amount.text.trim()),
        if (_type == 'expense') 'category': _category,
      });
      if (mounted) Navigator.pop(context, _date);
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error is ApiException
              ? error.message
              : 'Не удалось сохранить событие. Попробуйте ещё раз.',
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _amount.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_saving,
    child: SingleChildScrollView(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          24,
          24,
          24,
          24 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Новое событие',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: _type,
                decoration: const InputDecoration(labelText: 'Тип события'),
                items: [
                  for (final entry in operationTypes.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (value) => setState(() => _type = value!),
              ),
              TextFormField(
                controller: _name,
                enabled: !_saving,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'Название'),
                validator: (value) => value == null || value.trim().isEmpty
                    ? 'Введите название'
                    : null,
              ),
              TextFormField(
                controller: _amount,
                enabled: !_saving,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Сумма, ₽',
                  helperText: 'Целое число рублей',
                ),
                validator: (value) {
                  final amount = int.tryParse(value?.trim() ?? '');
                  return amount == null || amount <= 0 || amount > 2147483647
                      ? 'Введите целую сумму от 1 до 2147483647'
                      : null;
                },
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _saving
                    ? null
                    : () async {
                        final date = await showDatePicker(
                          context: context,
                          initialDate: _date,
                          firstDate: DateTime(1900),
                          lastDate: DateTime(9998, 12, 31),
                          helpText: 'Дата события',
                          cancelText: 'Отмена',
                          confirmText: 'Выбрать',
                        );
                        if (date != null && mounted) {
                          setState(() => _date = date);
                        }
                      },
                icon: const Icon(Icons.calendar_month),
                label: Text(_dateLabel(_date)),
              ),
              if (_type == 'expense')
                DropdownButtonFormField<String>(
                  initialValue: _category,
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Категория расхода',
                  ),
                  items: [
                    for (final category in expenseCategories)
                      DropdownMenuItem(
                        value: category,
                        child: Text(category, overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: _saving
                      ? null
                      : (value) => setState(() => _category = value!),
                ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 24),
              FilledButton(
                style: FilledButton.styleFrom(
                  shape: const StadiumBorder(),
                  padding: const EdgeInsets.all(16),
                ),
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Сохраняем…' : 'Сохранить событие'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
