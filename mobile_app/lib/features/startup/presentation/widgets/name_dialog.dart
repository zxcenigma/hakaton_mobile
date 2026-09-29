import 'package:flutter/material.dart';

import '../../../../app/theme/app_theme.dart';
import '../../../../logic/api/api.dart';
import '../../../../logic/profile/profile_store.dart';

class NameDialog extends StatefulWidget {
  const NameDialog({super.key, required this.api, required this.store});
  final ApiService api;
  final ProfileStore store;

  @override
  State<NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<NameDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  bool _busy = false;
  LocalProfile? _acceptedProfile;
  int _age = 18;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy || !_form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final profile =
          _acceptedProfile ??
          LocalProfile(username: _name.text.trim(), age: _age);
      if (_acceptedProfile == null) {
        await widget.api.signup(username: profile.username, age: profile.age);
        _acceptedProfile = profile;
      }
      // Retrying a failed local save must not register another account.
      await widget.store.save(profile);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = _acceptedProfile == null
              ? 'Не получилось сохранить имя. Попробуйте ещё раз.'
              : 'Данные приняты. Не удалось запомнить их на устройстве — попробуйте ещё раз.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _ageWord(int age) {
    if (age % 100 >= 11 && age % 100 <= 14) return 'лет';
    return switch (age % 10) {
      1 => 'год',
      2 || 3 || 4 => 'года',
      _ => 'лет',
    };
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: false,
    child: Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(30),
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFF59412E), Color(0xFF30251E)],
              ),
              borderRadius: BorderRadius.circular(30),
              border: Border.all(
                color: AppPalette.gold.withValues(alpha: 0.24),
              ),
            ),
            child: CustomPaint(
              painter: _WoodGrain(),
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(28),
                child: Form(
                  key: _form,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Center(
                        child: Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: AppPalette.gold.withValues(alpha: 0.10),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.pets_rounded,
                            color: AppPalette.gold,
                            size: 26,
                          ),
                        ),
                      ),
                      const SizedBox(height: 22),
                      const Text(
                        'Как к вам\nобращаться?',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 28,
                          height: 1.15,
                          fontWeight: FontWeight.w600,
                          color: AppPalette.ceramic,
                        ),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Давайте познакомимся.\nКопить вместе приятнее.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: AppPalette.ceramicShade,
                          fontSize: 15,
                          height: 1.5,
                        ),
                      ),
                      const SizedBox(height: 28),
                      TextFormField(
                        controller: _name,
                        enabled: !_busy && _acceptedProfile == null,
                        maxLength: 24,
                        textCapitalization: TextCapitalization.words,
                        textInputAction: TextInputAction.done,
                        autofillHints: const [AutofillHints.nickname],
                        onFieldSubmitted: (_) => _submit(),
                        style: const TextStyle(
                          color: AppPalette.ceramic,
                          fontSize: 18,
                        ),
                        cursorColor: AppPalette.gold,
                        decoration: InputDecoration(
                          labelText: 'Ваше имя',
                          hintText: 'Например, Саша',
                          counterText: '',
                          filled: true,
                          fillColor: const Color(
                            0xFF211B16,
                          ).withValues(alpha: 0.65),
                          labelStyle: const TextStyle(
                            color: AppPalette.ceramicShade,
                          ),
                          hintStyle: TextStyle(
                            color: AppPalette.ceramicShade.withValues(
                              alpha: 0.5,
                            ),
                          ),
                          errorMaxLines: 3,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 18,
                            vertical: 18,
                          ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide.none,
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: AppPalette.gold.withValues(alpha: 0.14),
                            ),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: const BorderSide(
                              color: AppPalette.gold,
                            ),
                          ),
                        ),
                        validator: (value) {
                          final name = value?.trim() ?? '';
                          if (name.isEmpty) return 'Введите имя';
                          return null;
                        },
                      ),
                      const SizedBox(height: 24),
                      const Text(
                        'Сколько вам лет?',
                        style: TextStyle(
                          color: AppPalette.ceramic,
                          fontSize: 18,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Center(
                        child: Text(
                          '$_age ${_ageWord(_age)}',
                          style: const TextStyle(
                            color: AppPalette.gold,
                            fontSize: 30,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          activeTrackColor: AppPalette.gold,
                          inactiveTrackColor: AppPalette.gold.withValues(
                            alpha: .15,
                          ),
                          thumbColor: AppPalette.gold,
                          overlayColor: AppPalette.gold.withValues(alpha: .12),
                          trackHeight: 4,
                          showValueIndicator: ShowValueIndicator.never,
                        ),
                        child: Semantics(
                          label: 'Возраст',
                          child: Slider(
                            value: _age.toDouble(),
                            min: 1,
                            max: 100,
                            divisions: 99,
                            semanticFormatterCallback: (value) =>
                                '${value.round()} ${_ageWord(value.round())}',
                            onChanged: _busy || _acceptedProfile != null
                                ? null
                                : (value) =>
                                      setState(() => _age = value.round()),
                          ),
                        ),
                      ),
                      const Row(
                        children: [
                          Expanded(
                            child: Text(
                              '1 год',
                              style: TextStyle(
                                color: AppPalette.ceramicShade,
                                fontSize: 12,
                              ),
                            ),
                          ),
                          Expanded(
                            child: Text(
                              '100 лет',
                              textAlign: TextAlign.right,
                              style: TextStyle(
                                color: AppPalette.ceramicShade,
                                fontSize: 12,
                              ),
                            ),
                          ),
                        ],
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 14),
                        Semantics(
                          liveRegion: true,
                          child: Text(
                            _error!,
                            style: const TextStyle(
                              color: Color(0xFFF0B7A4),
                              height: 1.4,
                            ),
                          ),
                        ),
                      ],
                      const SizedBox(height: 22),
                      FilledButton(
                        onPressed: _busy ? null : _submit,
                        style: FilledButton.styleFrom(
                          backgroundColor: AppPalette.gold,
                          foregroundColor: const Color(0xFF30251E),
                          disabledBackgroundColor: AppPalette.gold.withValues(
                            alpha: 0.5,
                          ),
                          disabledForegroundColor: const Color(0xFF30251E),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 20,
                            vertical: 17,
                          ),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                        child: Text(
                          _busy ? 'Знакомимся…' : 'Начать копить',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.labelLarge
                              ?.copyWith(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                                color: const Color(0xFF30251E),
                              ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class _WoodGrain extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFFE5C78F).withValues(alpha: 0.035)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (double y = -60; y < size.height + 60; y += 18) {
      canvas.drawPath(
        Path()
          ..moveTo(0, y)
          ..cubicTo(
            size.width * .3,
            y - 24,
            size.width * .65,
            y + 32,
            size.width,
            y + 8,
          ),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(_WoodGrain oldDelegate) => false;
}
