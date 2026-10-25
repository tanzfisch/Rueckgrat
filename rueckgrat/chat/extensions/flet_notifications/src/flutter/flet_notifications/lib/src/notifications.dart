import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class NotificationsControl extends FletService {
  NotificationsControl({required super.control});

  // FletNotificationsPlugin.java
  static const _channel = MethodChannel('rueckgrat/notifications');

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    switch (name) {
      case "request_permission":
        return await _channel.invokeMethod<bool>("requestPermission") ?? false;
      case "show":
        return await _channel.invokeMethod<bool>(
                "show", {"title": args["title"], "body": args["body"]}) ??
            false;
      default:
        throw Exception("Unknown Notifications method: $name");
    }
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    super.dispose();
  }
}
