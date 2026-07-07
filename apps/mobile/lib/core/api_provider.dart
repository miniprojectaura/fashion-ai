import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'config.dart';

/// Tracks whether we are online (authenticated with backend) or offline.
final connectionStateProvider = StateProvider<AppConnectionState>(
  (_) => AppConnectionState.connecting,
);

enum AppConnectionState { connecting, online, offline }

/// Tracks whether the user has completed auth (for gating the UI).
final isAuthenticatedProvider = StateProvider<bool>((_) => false);

/// Stores the current user ID for display/reference.
final currentUserIdProvider = StateProvider<String?>((_) => null);

/// The API client – always available (never throws).
final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(baseUrl: AppConfig.apiBaseUrl);
});

/// SharedPreferences keys
const _kAccessToken = 'aura_access_token';
const _kRefreshToken = 'aura_refresh_token';
const _kUserId = 'aura_user_id';
const _kDisplayName = 'aura_display_name';

/// Attempts to restore a cached session or create a new one.
/// Returns true if authenticated successfully.
final initApiProvider = FutureProvider<bool>((ref) async {
  final client = ref.read(apiClientProvider);
  final connState = ref.read(connectionStateProvider.notifier);
  final authState = ref.read(isAuthenticatedProvider.notifier);
  final userIdState = ref.read(currentUserIdProvider.notifier);
  connState.state = AppConnectionState.connecting;

  final prefs = await SharedPreferences.getInstance();
  final cachedToken = prefs.getString(_kAccessToken);
  final cachedUserId = prefs.getString(_kUserId);

  // Try cached token first
  if (cachedToken != null && cachedToken.isNotEmpty) {
    client.setToken(cachedToken);
    client.userId = cachedUserId;
    try {
      // Validate token
      await client.healthCheck();
      connState.state = AppConnectionState.online;
      authState.state = true;
      userIdState.state = cachedUserId;
      return true;
    } catch (_) {
      // Token expired — try refresh
      final refreshToken = prefs.getString(_kRefreshToken);
      if (refreshToken != null) {
        try {
          // TODO: implement refresh endpoint call when needed
          // For now, fall through to guest login
        } catch (_) {}
      }
    }
  }

  // No valid cached session — need fresh auth
  connState.state = AppConnectionState.offline;
  authState.state = false;
  return false;
});

/// Perform guest login, cache tokens, and update state.
Future<bool> performGuestLogin(
  ApiClient client,
  SharedPreferences prefs,
  StateController<AppConnectionState> connState,
  StateController<bool> authState,
  StateController<String?> userIdState, {
  String? displayName,
}) async {
  try {
    final data = await client.guestLogin(displayName: displayName);
    final token = data['access_token'] as String;
    final refreshToken = data['refresh_token'] as String?;
    final userId = data['user_id'] as String;

    // Cache for persistence across app restarts
    await prefs.setString(_kAccessToken, token);
    if (refreshToken != null) await prefs.setString(_kRefreshToken, refreshToken);
    await prefs.setString(_kUserId, userId);
    if (displayName != null) await prefs.setString(_kDisplayName, displayName);

    connState.state = AppConnectionState.online;
    authState.state = true;
    userIdState.state = userId;
    return true;
  } catch (_) {
    connState.state = AppConnectionState.offline;
    return false;
  }
}
