import 'dart:convert';

import 'package:dio/dio.dart';

class ApiClient {
  ApiClient({required String baseUrl, String? token})
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 60),
          receiveTimeout: const Duration(seconds: 120),
          headers: {
            if (token != null) 'Authorization': 'Bearer $token',
          },
        ));

  final Dio _dio;
  String? userId;

  void setToken(String token) {
    _dio.options.headers['Authorization'] = 'Bearer $token';
  }

  /// Simple health check — just verifies server is reachable
  Future<bool> healthCheck() async {
    final resp = await _dio.get('/health');
    return resp.statusCode == 200;
  }

  Future<Map<String, dynamic>> guestLogin({String? displayName}) async {
    final resp = await _dio.post('/api/v1/auth/guest', data: {
      'display_name': displayName ?? 'User',
    });
    final data = resp.data as Map<String, dynamic>;
    setToken(data['access_token'] as String);
    userId = data['user_id'] as String?;
    return data;
  }

  Future<Map<String, dynamic>> sendChat({
    required String message,
    String? sessionId,
    String language = 'te',
  }) async {
    final resp = await _dio.post('/api/v1/chat/message', data: {
      'message': message,
      if (sessionId != null) 'session_id': sessionId,
      'language': language,
    });
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> generateOutfits({
    required String brief,
    int numVariants = 4,
  }) async {
    final resp = await _dio.post('/api/v1/design/outfits', data: {
      'brief': brief,
      'num_variants': numVariants,
    });
    return resp.data as Map<String, dynamic>;
  }

  Future<List<dynamic>> searchProducts(String query, {double? maxPrice}) async {
    final resp = await _dio.post('/api/v1/search/products', data: {
      'query': query,
      if (maxPrice != null) 'max_price_inr': maxPrice,
    });
    return (resp.data['results'] as List?) ?? [];
  }

  Future<Map<String, dynamic>> uploadAvatar({
    required String frontPath,
    String? sidePath,
  }) async {
    final form = FormData.fromMap({
      'front': await MultipartFile.fromFile(frontPath, filename: 'front.jpg'),
      if (sidePath != null)
        'side': await MultipartFile.fromFile(sidePath, filename: 'side.jpg'),
    });
    final resp = await _dio.post('/api/v1/avatar/upload', data: form);
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> analyzeBody({
    required String frontPath,
    String? sidePath,
    double heightCm = 165.0,
  }) async {
    final form = FormData.fromMap({
      'front': await MultipartFile.fromFile(frontPath, filename: 'front.jpg'),
      if (sidePath != null)
        'side': await MultipartFile.fromFile(sidePath, filename: 'side.jpg'),
      'height_cm': heightCm.toString(),
    });
    final resp = await _dio.post('/api/v1/avatar/analyze', data: form);
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> checkImageQuality(String imagePath) async {
    final form = FormData.fromMap({
      'photo': await MultipartFile.fromFile(imagePath, filename: 'check.jpg'),
    });
    final resp = await _dio.post('/api/v1/avatar/check-quality', data: form);
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getMeasurements() async {
    final resp = await _dio.get('/api/v1/avatar/measurements');
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> tailoringGuide({
    required String garmentType,
    String fabric = 'silk',
    Map<String, dynamic>? measurements,
  }) async {
    final resp = await _dio.post('/api/v1/tailor/guide', data: {
      'garment_type': garmentType,
      'fabric': fabric,
      'measurements': measurements ?? {'chest_cm': 88, 'waist_cm': 72, 'hip_cm': 96},
    });
    return resp.data as Map<String, dynamic>;
  }

  Future<void> styleFeedback({required bool liked, List<String> tags = const []}) async {
    await _dio.post('/api/v1/feedback/style', data: {
      'liked': liked,
      'tags': tags,
    });
  }

  Future<List<dynamic>> listWardrobe() async {
    final resp = await _dio.get('/api/v1/wardrobe/');
    return (resp.data['items'] as List?) ?? [];
  }

  Future<void> addWardrobeItem({required String name, String? category}) async {
    await _dio.post('/api/v1/wardrobe/', data: {
      'name': name,
      if (category != null) 'category': category,
    });
  }

  Future<Map<String, dynamic>> designFlow({
    required String message,
    String language = 'te',
  }) async {
    final resp = await _dio.post('/api/v1/session/design-flow', data: {
      'message': message,
      'language': language,
    });
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> serviceStatus() async {
    final resp = await _dio.get('/api/v1/status/services');
    return resp.data as Map<String, dynamic>;
  }

  /// Decode base64 PNG from outfit variant for Image.memory
  static List<int>? decodeVariantImage(Map<String, dynamic> variant) {
    final b64 = variant['image_base64'] as String?;
    if (b64 == null) return null;
    return base64Decode(b64);
  }

  /// Voice conversation — send audio, get transcript + reply audio (base64)
  /// Response includes: transcript, reply_text, reply_audio_b64,
  /// detected_language, asr_engine, tts_engine, outfit_state
  Future<Map<String, dynamic>> voiceConverse({
    required String audioPath,
    required String sessionId,
    String language = '',  // empty = auto-detect
  }) async {
    final form = FormData.fromMap({
      'audio': await MultipartFile.fromFile(audioPath, filename: 'audio.wav'),
      'session_id': sessionId,
      'language': language,
    });
    final resp = await _dio.post('/api/v1/voice/converse', data: form);
    return resp.data as Map<String, dynamic>;
  }

  /// Text-based stylist conversation — also returns TTS audio (base64)
  /// Response includes: transcript, reply_text, reply_audio_b64,
  /// detected_language, asr_engine, tts_engine, outfit_state
  Future<Map<String, dynamic>> voiceConverseText({
    required String message,
    required String sessionId,
    String language = 'te',
  }) async {
    final resp = await _dio.post('/api/v1/voice/converse-text', data: {
      'message': message,
      'session_id': sessionId,
      'language': language,
    });
    return resp.data as Map<String, dynamic>;
  }

  /// Finalize outfit — lock spec, generate image, save to wardrobe
  Future<Map<String, dynamic>> finalizeOutfit({
    required String sessionId,
  }) async {
    final resp = await _dio.post('/api/v1/voice/finalize', data: {
      'session_id': sessionId,
    });
    return resp.data as Map<String, dynamic>;
  }

  // ── Chat History ─────────────────────────────────────────────

  /// List all chat sessions for the current user
  Future<List<Map<String, dynamic>>> listChatSessions() async {
    final resp = await _dio.get('/api/v1/voice/sessions');
    final data = resp.data as Map<String, dynamic>;
    return ((data['sessions'] as List?) ?? [])
        .map((s) => s as Map<String, dynamic>)
        .toList();
  }

  /// Get all messages for a specific session
  Future<List<Map<String, dynamic>>> getChatMessages(String sessionId) async {
    final resp = await _dio.get('/api/v1/voice/sessions/$sessionId/messages');
    final data = resp.data as Map<String, dynamic>;
    return ((data['messages'] as List?) ?? [])
        .map((m) => m as Map<String, dynamic>)
        .toList();
  }

  /// Create a new chat session
  Future<String> createChatSession() async {
    final resp = await _dio.post('/api/v1/voice/sessions', data: {});
    final data = resp.data as Map<String, dynamic>;
    return data['session_id'] as String;
  }
}
