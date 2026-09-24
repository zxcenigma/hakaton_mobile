import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../../../app/theme/app_theme.dart';

class DepositSheet extends StatefulWidget {
  const DepositSheet({super.key});
  @override
  State<DepositSheet> createState() => _DepositSheetState();
}

class _DepositSheetState extends State<DepositSheet> {
  final _amount = TextEditingController();
  final _form = GlobalKey<FormState>();

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  void _submit() {
    if (_form.currentState!.validate()) {
      Navigator.pop(context, int.parse(_amount.text));
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.fromLTRB(
      24,
      8,
      24,
      MediaQuery.viewInsetsOf(context).bottom + 24,
    ),
    child: SafeArea(
      child: SingleChildScrollView(
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Пополнить копилку',
                style: TextStyle(
                  color: AppPalette.gold,
                  fontSize: 22,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Сколько рублей положим котику?',
                style: TextStyle(color: AppPalette.ceramic),
              ),
              const SizedBox(height: 20),
              TextFormField(
                controller: _amount,
                autofocus: true,
                style: const TextStyle(color: AppPalette.ceramic),
                keyboardType: TextInputType.number,
                textInputAction: TextInputAction.done,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(7),
                ],
                decoration: const InputDecoration(
                  labelText: 'Сумма',
                  suffixText: '₽',
                  labelStyle: TextStyle(color: AppPalette.gold),
                  suffixStyle: TextStyle(color: AppPalette.gold),
                  enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: AppPalette.podiumTop),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: AppPalette.gold),
                  ),
                ),
                validator: (text) {
                  final value = int.tryParse(text ?? '');
                  return value == null || value < 1 || value > 1000000
                      ? 'Введите от 1 до 1 000 000 ₽'
                      : null;
                },
                onFieldSubmitted: (_) => _submit(),
              ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _submit,
                style: FilledButton.styleFrom(
                  backgroundColor: AppPalette.gold,
                  foregroundColor: AppPalette.stageBackground,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                  padding: const EdgeInsets.all(16),
                ),
                child: const Text('Положить в копилку'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
