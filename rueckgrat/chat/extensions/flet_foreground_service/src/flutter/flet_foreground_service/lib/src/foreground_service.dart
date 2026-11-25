import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

class ForegroundServiceControl extends FletService {
  ForegroundServiceControl({required super.control});

  static const int _serviceId = 4711;
  static const Map<String, ForegroundServiceTypes> _typesByName = {
    "specialUse": ForegroundServiceTypes.specialUse,
    "microphone": ForegroundServiceTypes.microphone,
  };

  List<String>? _types; // of the service started here, they are fixed while it runs

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "start":
        return await _start(
            args["title"], args["text"], List<String>.from(args["types"]));
      case "stop":
        final result = await FlutterForegroundTask.stopService();
        _types = null;
        return result is ServiceRequestSuccess;
      default:
        throw Exception("Unknown ForegroundService method: $name");
    }
  }

  Future<bool> _start(String title, String text, List<String> types) async {
    // Android 13+: without the permission the service still runs, only its notification is hidden.
    if (await FlutterForegroundTask.checkNotificationPermission() !=
        NotificationPermission.granted) {
      await FlutterForegroundTask.requestNotificationPermission();
    }

    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'rueckgrat_connection',
        channelName: 'Connection',
        channelDescription:
            'Shown while logged in, keeps the connection to the hub and the microphone running in the background.',
      ),
      iosNotificationOptions: const IOSNotificationOptions(),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.nothing(),
        allowWakeLock: true, // keep the CPU running with the screen off
        allowWifiLock: true, // keep the Wi-Fi radio awake with the screen off
        allowAutoRestart: false, // never come back as an empty notification after a kill
        stopWithTask: false, // true would stop the service whenever the app leaves the foreground (screen lock!)
      ),
    );

    if (await FlutterForegroundTask.isRunningService) {
      if (listEquals(_types, types)) {
        await FlutterForegroundTask.updateService(
            notificationTitle: title, notificationText: text);
        return true;
      }
      // updateService can't change the types: restart with the new ones (the app is visible, so it may start)
      await FlutterForegroundTask.stopService();
    }

    final result = await FlutterForegroundTask.startService(
      serviceId: _serviceId,
      serviceTypes: [for (final t in types) _typesByName[t]!],
      notificationTitle: title,
      notificationText: text,
    );
    if (result is ServiceRequestFailure) {
      debugPrint("ForegroundService: start failed: ${result.error}");
      _types = null;
      return false;
    }
    _types = types;
    return true;
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    FlutterForegroundTask.stopService();
    super.dispose();
  }
}
