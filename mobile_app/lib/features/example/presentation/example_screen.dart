import 'package:flutter/material.dart';

import '../../../shared/widgets/oval_app_bar.dart';
import '../../../app/navigation/app_sections.dart';
import '../../home/presentation/widgets/stage_background.dart';

class ExampleScreen extends StatelessWidget {
  const ExampleScreen({required this.number, super.key});

  final int number;

  @override
  Widget build(BuildContext context) {
    final title = AppSections.title(number);
    return Scaffold(
      body: Stack(
        children: [
          const Positioned.fill(child: StageBackground()),
          SafeArea(
            child: Column(
              children: [
                OvalAppBar(title: title),
                Expanded(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      return SingleChildScrollView(
                        child: ConstrainedBox(
                          constraints: BoxConstraints(
                            minHeight: constraints.maxHeight,
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Center(
                              child: Text(
                                '$title — здесь появится содержимое',
                                textAlign: TextAlign.center,
                                style: Theme.of(context).textTheme.bodyLarge,
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
