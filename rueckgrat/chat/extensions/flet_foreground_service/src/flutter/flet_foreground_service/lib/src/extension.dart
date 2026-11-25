import 'package:flet/flet.dart';

import 'foreground_service.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "ForegroundService":
        return ForegroundServiceControl(control: control);
      default:
        return null;
    }
  }
}
