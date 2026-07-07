import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_provider.dart';
import '../../core/aura_background.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen>
    with TickerProviderStateMixin {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _messages = <Map<String, dynamic>>[];
  final _voiceSessionId = 'voice-default';
  bool _loading = false;
  String _detectedLang = 'en'; // Auto-updated from responses
  final _audioPlayer = AudioPlayer();
  late final AnimationController _typingCtrl;
  late final AnimationController _pulseCtrl;

  // Audio recording
  final _recorder = AudioRecorder();
  bool _isRecording = false;
  String? _recordingPath;

  bool _isPlayingResponse = false;

  @override
  void initState() {
    super.initState();
    _typingCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _audioPlayer.dispose();
    _typingCtrl.dispose();
    _pulseCtrl.dispose();
    _recorder.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ── Text send ──────────────────────────────────────────────────
  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;

    final connState = ref.read(connectionStateProvider);
    if (connState != AppConnectionState.online) {
      _addMessage('assistant',
          '⚠️ You are offline. Please connect to the server first.');
      return;
    }

    final api = ref.read(apiClientProvider);
    setState(() {
      _loading = true;
      _messages.add({'role': 'user', 'text': text});
      _controller.clear();
    });
    _scrollToBottom();

    try {
      final resp = await api.voiceConverseText(
        message: text,
        sessionId: _voiceSessionId,
        language: _detectedLang,
      );

      // Update detected language from server response
      final serverLang = resp['detected_language'] as String?;
      if (serverLang != null && serverLang.isNotEmpty) {
        _detectedLang = serverLang;
      }

      final replyText = resp['reply_text'] as String? ?? '';
      _addMessage('assistant', replyText);

      // Show outfit state and trigger finalize
      final outfitState = resp['outfit_state'] as Map<String, dynamic>?;
      if (outfitState != null) {
        final stage = outfitState['stage'] as String? ?? '';
        if (stage == 'finalized') {
          _addMessage('assistant',
              '✅ Outfit finalized! Generating your design...');
          await _triggerFinalize(api);
        }
      }

      // Play reply audio if available (now base64 inline)
      await _playAudioFromResponse(resp);
    } catch (e) {
      _addMessage('assistant',
          '❌ Could not reach the server.\nPlease check your connection.');
    } finally {
      setState(() => _loading = false);
    }
  }

  void _addMessage(String role, String text, {String? imageB64, List<Map<String, dynamic>>? products, Map<String, dynamic>? tailoring, Map<String, dynamic>? spec}) {
    setState(() {
      _messages.add({
        'role': role,
        'text': text,
        if (imageB64 != null) 'image_b64': imageB64,
        if (products != null) 'products': products,
        if (tailoring != null) 'tailoring': tailoring,
        if (spec != null) 'spec': spec,
      });
    });
    _scrollToBottom();
  }

  // ── Audio recording (raw WAV via record package) ───────────────
  Future<void> _toggleRecording() async {
    if (_isRecording) {
      await _stopAndSend();
    } else {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    try {
      if (!await _recorder.hasPermission()) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  '🎤 Microphone permission denied. Please enable it in Settings.'),
            ),
          );
        }
        return;
      }

      final dir = await getTemporaryDirectory();
      _recordingPath = p.join(dir.path, 'aura_voice_${DateTime.now().millisecondsSinceEpoch}.wav');

      const config = RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
        bitRate: 256000,
      );

      await _recorder.start(config, path: _recordingPath!);
      setState(() => _isRecording = true);
    } catch (e) {
      debugPrint('Recording start failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to start recording: $e')),
        );
      }
    }
  }

  Future<void> _stopAndSend() async {
    try {
      final path = await _recorder.stop();
      setState(() => _isRecording = false);

      if (path == null || path.isEmpty) return;

      final file = File(path);
      if (!await file.exists()) return;
      final fileSize = await file.length();
      if (fileSize < 100) {
        _addMessage('assistant', '🎤 Recording too short. Try speaking a bit longer.');
        return;
      }

      // Show user's voice message indicator
      _addMessage('user', '🎤 Voice message sent');

      final connState = ref.read(connectionStateProvider);
      if (connState != AppConnectionState.online) {
        _addMessage('assistant',
            '⚠️ You are offline. Please connect to the server first.');
        return;
      }

      setState(() => _loading = true);

      final api = ref.read(apiClientProvider);
      try {
        final resp = await api.voiceConverse(
          audioPath: path,
          sessionId: _voiceSessionId,
        );

        final transcript = resp['transcript'] as String? ?? '';
        final replyText = resp['reply_text'] as String? ?? '';
        final detectedLang = resp['detected_language'] as String? ?? '';
        final asrEngine = resp['asr_engine'] as String? ?? '';
        final ttsEngine = resp['tts_engine'] as String? ?? '';
        debugPrint('[voice] ASR=$asrEngine, TTS=$ttsEngine, lang=$detectedLang');

        // Replace the "voice message sent" with actual transcript
        if (_messages.isNotEmpty && _messages.last['text'] == '🎤 Voice message sent') {
          setState(() {
            _messages.last['text'] = '🎤 "$transcript"';
          });
        }

        _addMessage('assistant', replyText);

        // Show outfit state and trigger finalize
        final outfitState = resp['outfit_state'] as Map<String, dynamic>?;
        if (outfitState != null) {
          final stage = outfitState['stage'] as String? ?? '';
          if (stage == 'finalized') {
            _addMessage('assistant',
                '✅ Outfit finalized! Generating your design...');
            await _triggerFinalize(api);
          }
        }

        // Auto-play reply audio
        await _playAudioFromResponse(resp);
      } catch (e) {
        _addMessage('assistant',
            '❌ Could not reach the server.\nPlease check your connection.');
      } finally {
        setState(() => _loading = false);
      }

      // Cleanup temp file
      try { await file.delete(); } catch (_) {}
    } catch (e) {
      setState(() => _isRecording = false);
      debugPrint('Recording stop/send failed: $e');
    }
  }

  // ── Audio playback from base64 ─────────────────────────────────
  Future<void> _playAudioFromResponse(Map<String, dynamic> resp) async {
    final audioB64 = resp['reply_audio_b64'] as String?;
    if (audioB64 == null || audioB64.isEmpty) return;

    try {
      setState(() => _isPlayingResponse = true);
      final audioBytes = base64Decode(audioB64);
      final dir = await getTemporaryDirectory();
      final audioFile = File(p.join(dir.path, 'aura_reply_${DateTime.now().millisecondsSinceEpoch}.wav'));
      await audioFile.writeAsBytes(audioBytes);
      await _audioPlayer.play(DeviceFileSource(audioFile.path));

      // Listen for completion
      _audioPlayer.onPlayerComplete.listen((_) {
        if (mounted) {
          setState(() => _isPlayingResponse = false);
        }
        // Clean up temp file
        try { audioFile.deleteSync(); } catch (_) {}
      });
    } catch (e) {
      debugPrint('Audio playback failed: $e');
      setState(() => _isPlayingResponse = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final connState = ref.watch(connectionStateProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Animated AURA logo dot
            Container(
              width: 10,
              height: 10,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: connState == AppConnectionState.online
                    ? const Color(0xFFD4AF37)
                    : Colors.grey,
                boxShadow: connState == AppConnectionState.online
                    ? [
                        BoxShadow(
                          color: const Color(0xFFD4AF37).withValues(alpha: 0.5),
                          blurRadius: 8,
                          spreadRadius: 1,
                        ),
                      ]
                    : null,
              ),
            ),
            const Text('AURA'),
            Text(
              '  Stylist',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.4),
                fontSize: 14,
                fontWeight: FontWeight.w300,
              ),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          // Recording status banner
          if (_isRecording) _buildRecordingBanner(),
          // Playing response indicator
          if (_isPlayingResponse) _buildPlayingBanner(),
          Expanded(
            child: _messages.isEmpty
                ? _buildEmptyState()
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                    itemCount: _messages.length + (_loading ? 1 : 0),
                    itemBuilder: (_, i) {
                      if (i == _messages.length && _loading) {
                        return _buildTypingIndicator();
                      }
                      return _buildMessageBubble(_messages[i]);
                    },
                  ),
          ),
          _buildInputBar(),
        ],
      ),
    );
  }
  // ── Finalize trigger — calls API and shows rich results ─────────
  Future<void> _triggerFinalize(dynamic api) async {
    try {
      final result = await api.finalizeOutfit(sessionId: _voiceSessionId);

      // Show outfit image — prefer inline base64, fallback to URL
      final outfitB64 = result['outfit_image_b64'] as String?;
      final imageUrl = result['image_url'] as String?;
      if (outfitB64 != null && outfitB64.isNotEmpty) {
        setState(() {
          _messages.add({'role': 'result', 'type': 'tryon', 'data': outfitB64});
        });
        _scrollToBottom();
      } else if (imageUrl != null && imageUrl.isNotEmpty) {
        setState(() {
          _messages.add({'role': 'result', 'type': 'image', 'url': imageUrl});
        });
        _scrollToBottom();
      }

      // Show try-on image if available
      final tryonB64 = result['tryon_image_b64'] as String?;
      if (tryonB64 != null && tryonB64.isNotEmpty) {
        setState(() {
          _messages.add({'role': 'result', 'type': 'tryon', 'data': tryonB64});
        });
        _scrollToBottom();
      }

      // Show tailoring measurements
      final tailoring = result['tailoring'] as Map<String, dynamic>?;
      if (tailoring != null) {
        setState(() {
          _messages.add({
            'role': 'result',
            'type': 'tailoring',
            'text': _formatTailoring(tailoring),
          });
        });
        _scrollToBottom();
      }

      // Show product links
      final webMatches = result['web_matches'] as List?;
      if (webMatches != null && webMatches.isNotEmpty) {
        setState(() {
          _messages.add({
            'role': 'result',
            'type': 'products',
            'text': _formatProducts(webMatches),
            'links': webMatches.map((m) => (m as Map)['url']?.toString() ?? '').join('|'),
            'names': webMatches.map((m) => (m as Map)['name']?.toString() ?? 'Product').join('|'),
          });
        });
        _scrollToBottom();
      }

      // Show reasoning (expandable)
      final reasoning = result['reasoning'] as String?;
      if (reasoning != null && reasoning.contains('<think>')) {
        final thinkMatch = RegExp(r'<think>(.*?)</think>', dotAll: true).firstMatch(reasoning);
        if (thinkMatch != null) {
          setState(() {
            _messages.add({
              'role': 'result',
              'type': 'reasoning',
              'text': thinkMatch.group(1)?.trim() ?? '',
            });
          });
          _scrollToBottom();
        }
      }
    } catch (e) {
      debugPrint('Finalize failed: $e');
      _addMessage('assistant', '⚠️ Could not generate final design. Please try again.');
    }
  }

  String _formatTailoring(Map<String, dynamic> tailoring) {
    final buf = StringBuffer();
    buf.writeln('📐 Tailoring Measurements');
    buf.writeln('');

    final cut = tailoring['cut_measurements'] as Map<String, dynamic>?;
    if (cut != null) {
      buf.writeln('Cut Sizes:');
      cut.forEach((k, v) => buf.writeln('  ${k.replaceAll('_', ' ')}: ${v}cm'));
      buf.writeln('');
    }

    final fabric = tailoring['fabric_requirement'] as Map<String, dynamic>?;
    if (fabric != null) {
      buf.writeln('Fabric: ${fabric['total_meters']}m needed');
      if (fabric['notes'] != null) buf.writeln('  ${fabric['notes']}');
      buf.writeln('');
    }

    final darts = tailoring['dart_placements'] as List?;
    if (darts != null && darts.isNotEmpty) {
      buf.writeln('Darts:');
      for (final d in darts) {
        buf.writeln('  • $d');
      }
    }
    return buf.toString().trim();
  }

  String _formatProducts(List products) {
    final buf = StringBuffer();
    buf.writeln('🛍️ Shop Similar');
    for (var i = 0; i < products.length && i < 5; i++) {
      final p = products[i] as Map;
      final name = p['name'] ?? 'Product';
      final platform = p['platform'] ?? '';
      final price = p['price_inr'];
      buf.write('  ${i + 1}. $name');
      if (platform.isNotEmpty) buf.write(' ($platform)');
      if (price != null) buf.write(' — ₹${price.toStringAsFixed(0)}');
      buf.writeln('');
    }
    return buf.toString().trim();
  }

  Widget _buildResultCard(Map<String, dynamic> m) {
    final type = (m['type'] ?? '') as String;

    if (type == 'image' || type == 'tryon') {
      final label = type == 'tryon' ? '👗 Virtual Try-On' : '🎨 Design Preview';
      Widget imageWidget;
      if (type == 'tryon') {
        final bytes = base64Decode((m['data'] ?? '').toString());
        imageWidget = Image.memory(Uint8List.fromList(bytes), fit: BoxFit.cover);
      } else {
        imageWidget = Image.network((m['url'] ?? '').toString(), fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => const Center(child: Icon(Icons.broken_image, color: Colors.white30)));
      }
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _resultLabel(label),
            ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: SizedBox(
                width: double.infinity,
                height: 300,
                child: imageWidget,
              ),
            ),
          ],
        ),
      );
    }

    if (type == 'products') {
      final links = (m['links'] ?? '').toString().split('|');
      final names = (m['names'] ?? '').toString().split('|');
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(colors: [
              const Color(0xFF1A237E).withValues(alpha: 0.4),
              const Color(0xFF0D47A1).withValues(alpha: 0.3),
            ]),
            border: Border.all(color: const Color(0xFF42A5F5).withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _resultLabel('🛍️ Shop Similar'),
              const SizedBox(height: 8),
              ...List.generate(
                links.length > 5 ? 5 : links.length,
                (i) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: GestureDetector(
                    onTap: () async {
                      final url = links[i].trim();
                      if (url.isNotEmpty) {
                        try {
                          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
                        } catch (_) {}
                      }
                    },
                    child: Row(
                      children: [
                        const Icon(Icons.shopping_bag_outlined, color: Color(0xFF42A5F5), size: 16),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            i < names.length ? names[i].trim() : 'Product ${i + 1}',
                            style: const TextStyle(
                              color: Color(0xFF90CAF9),
                              fontSize: 13,
                              decoration: TextDecoration.underline,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const Icon(Icons.open_in_new, color: Color(0xFF42A5F5), size: 14),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (type == 'reasoning') {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: _ExpandableReasoningCard(reasoning: (m['text'] ?? '').toString()),
      );
    }

    // Default: tailoring card
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          gradient: LinearGradient(colors: [
            const Color(0xFF1B5E20).withValues(alpha: 0.4),
            const Color(0xFF2E7D32).withValues(alpha: 0.3),
          ]),
          border: Border.all(color: const Color(0xFF66BB6A).withValues(alpha: 0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _resultLabel('📐 Tailoring Measurements'),
            const SizedBox(height: 8),
            Text(
              (m['text'] ?? '').toString(),
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.85),
                fontSize: 13,
                height: 1.5,
                fontFamily: 'monospace',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _resultLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        text,
        style: const TextStyle(
          color: Color(0xFFD4AF37),
          fontSize: 14,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.3,
        ),
      ),
    );
  }

  Widget _buildRecordingBanner() {
    return AnimatedBuilder(
      animation: _pulseCtrl,
      builder: (context, child) {
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                Color.lerp(
                  const Color(0xFF8B1538).withValues(alpha: 0.8),
                  const Color(0xFFFF1744).withValues(alpha: 0.9),
                  _pulseCtrl.value,
                )!,
                const Color(0xFF4A148C).withValues(alpha: 0.9),
              ],
            ),
          ),
          child: Row(
            children: [
              // Animated recording dot
              Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.red.withValues(alpha: 0.6 + 0.4 * _pulseCtrl.value),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.red.withValues(alpha: 0.4 * _pulseCtrl.value),
                      blurRadius: 8 + 4 * _pulseCtrl.value,
                      spreadRadius: 1,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Listening...',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.9),
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Speak naturally in any language • Tap mic to send',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.5),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              // Stop button
              GestureDetector(
                onTap: _stopAndSend,
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                  ),
                  child: const Icon(Icons.stop_rounded, color: Colors.white, size: 20),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildPlayingBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            const Color(0xFF1B5E20).withValues(alpha: 0.8),
            const Color(0xFF004D40).withValues(alpha: 0.8),
          ],
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.volume_up_rounded, color: Colors.greenAccent, size: 20),
          const SizedBox(width: 10),
          Text(
            'AURA is speaking...',
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.9),
              fontSize: 13,
              fontWeight: FontWeight.w500,
            ),
          ),
          const Spacer(),
          GestureDetector(
            onTap: () async {
              await _audioPlayer.stop();
              setState(() => _isPlayingResponse = false);
            },
            child: Icon(Icons.close, color: Colors.white.withValues(alpha: 0.6), size: 18),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // AURA brand icon
          Container(
            width: 80,
            height: 80,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFF8B1538), Color(0xFF4A148C)],
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF8B1538).withValues(alpha: 0.4),
                  blurRadius: 24,
                  spreadRadius: 2,
                ),
              ],
            ),
            child: const Icon(
              Icons.auto_awesome,
              color: Colors.white,
              size: 36,
            ),
          ),
          const SizedBox(height: 24),
          Text(
            'Your AI Fashion Stylist',
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  letterSpacing: -0.3,
                ),
          ),
          const SizedBox(height: 12),
          Text(
            'Ask me about outfits, styling tips,\nor body-type recommendations',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 20),
          // Voice-first hint
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              gradient: LinearGradient(
                colors: [
                  const Color(0xFF8B1538).withValues(alpha: 0.3),
                  const Color(0xFF4A148C).withValues(alpha: 0.2),
                ],
              ),
              border: Border.all(color: const Color(0xFF8B1538).withValues(alpha: 0.4)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.mic_rounded, color: const Color(0xFFD4AF37).withValues(alpha: 0.9), size: 22),
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Tap the mic to talk',
                      style: TextStyle(color: Colors.white.withValues(alpha: 0.9), fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                    Text(
                      'Telugu • Hindi • English • Tinglish',
                      style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          // Quick action chips
          Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.center,
            children: [
              _quickChip('👗 Wedding outfit'),
              _quickChip('🎨 Color for my skin tone'),
              _quickChip('📐 Body type dressing'),
              _quickChip('💰 Budget outfit under ₹5000'),
            ],
          ),
        ],
      ),
    );
  }

  Widget _quickChip(String label) {
    return GestureDetector(
      onTap: () {
        _controller.text = label.replaceAll(RegExp(r'^[^\s]+ '), '');
        _send();
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          color: Colors.white.withValues(alpha: 0.06),
          border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.7),
            fontSize: 13,
          ),
        ),
      ),
    );
  }

  Widget _buildMessageBubble(Map<String, dynamic> m) {
    // Route result cards to rich display widgets
    if (m['role'] == 'result') {
      return _buildResultCard(m);
    }
    final isUser = m['role'] == 'user';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...[
            // AI avatar
            Container(
              width: 28,
              height: 28,
              margin: const EdgeInsets.only(right: 8, bottom: 4),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: const LinearGradient(
                  colors: [Color(0xFF8B1538), Color(0xFF4A148C)],
                ),
                boxShadow: [
                  BoxShadow(
                    color:
                        const Color(0xFF8B1538).withValues(alpha: 0.3),
                    blurRadius: 8,
                  ),
                ],
              ),
              child: const Icon(Icons.auto_awesome, size: 14, color: Colors.white),
            ),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.all(14),
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.75,
              ),
              decoration:
                  isUser ? AuraTheme.userBubble : AuraTheme.assistantBubble,
              child: Text(
                (m['text'] ?? '').toString(),
                style: TextStyle(
                  color: isUser ? Colors.white : Colors.white.withValues(alpha: 0.9),
                  fontSize: 14.5,
                  height: 1.4,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTypingIndicator() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            margin: const EdgeInsets.only(right: 8),
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              gradient: LinearGradient(
                colors: [Color(0xFF8B1538), Color(0xFF4A148C)],
              ),
            ),
            child: const Icon(Icons.auto_awesome, size: 14, color: Colors.white),
          ),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: AuraTheme.assistantBubble,
            child: AnimatedBuilder(
              animation: _typingCtrl,
              builder: (context, _) {
                return Row(
                  mainAxisSize: MainAxisSize.min,
                  children: List.generate(3, (i) {
                    final delay = i * 0.2;
                    final t = (_typingCtrl.value + delay) % 1.0;
                    final y = -4.0 * (t < 0.5 ? t : 1.0 - t);
                    return Transform.translate(
                      offset: Offset(0, y * 2),
                      child: Container(
                        width: 7,
                        height: 7,
                        margin: EdgeInsets.only(right: i < 2 ? 5 : 0),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: const Color(0xFFD4AF37)
                              .withValues(alpha: 0.4 + 0.4 * (1 - t)),
                        ),
                      ),
                    );
                  }),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
      decoration: BoxDecoration(
        color: const Color(0xFF121218).withValues(alpha: 0.9),
        border: Border(
          top: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
        ),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            // Voice-first: prominent mic button
            _buildMicButton(),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: _controller,
                style: const TextStyle(color: Colors.white, fontSize: 14.5),
                decoration: InputDecoration(
                  hintText: _isRecording
                      ? 'Recording...'
                      : 'Type or tap mic to speak…',
                ),
                onSubmitted: (_) => _send(),
                enabled: !_isRecording,
              ),
            ),
            const SizedBox(width: 8),
            // Send button (for text)
            Container(
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF8B1538), Color(0xFF6A0F2B)],
                ),
                borderRadius: BorderRadius.circular(16),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF8B1538).withValues(alpha: 0.4),
                    blurRadius: 12,
                    offset: const Offset(0, 3),
                  ),
                ],
              ),
              child: IconButton(
                icon: const Icon(Icons.arrow_upward_rounded,
                    color: Colors.white, size: 20),
                onPressed: _send,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMicButton() {
    return AnimatedBuilder(
      animation: _pulseCtrl,
      builder: (context, child) {
        final scale = _isRecording ? 1.0 + 0.08 * _pulseCtrl.value : 1.0;
        return Transform.scale(
          scale: scale,
          child: Container(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: _isRecording
                  ? LinearGradient(
                      colors: [
                        Colors.red.shade700,
                        Colors.red.shade900,
                      ],
                    )
                  : const LinearGradient(
                      colors: [Color(0xFFD4AF37), Color(0xFFB8860B)],
                    ),
              boxShadow: [
                BoxShadow(
                  color: _isRecording
                      ? Colors.red.withValues(alpha: 0.4 + 0.2 * _pulseCtrl.value)
                      : const Color(0xFFD4AF37).withValues(alpha: 0.3),
                  blurRadius: _isRecording ? 16 + 4 * _pulseCtrl.value : 12,
                  spreadRadius: _isRecording ? 2 : 1,
                ),
              ],
            ),
            child: IconButton(
              icon: Icon(
                _isRecording ? Icons.stop_rounded : Icons.mic_rounded,
                color: Colors.white,
                size: 24,
              ),
              onPressed: _toggleRecording,
              tooltip: _isRecording ? 'Stop & send' : 'Tap to speak',
            ),
          ),
        );
      },
    );
  }
}

/// Expandable card showing the AI's chain-of-thought reasoning.
class _ExpandableReasoningCard extends StatefulWidget {
  const _ExpandableReasoningCard({required this.reasoning});
  final String reasoning;

  @override
  State<_ExpandableReasoningCard> createState() => _ExpandableReasoningCardState();
}

class _ExpandableReasoningCardState extends State<_ExpandableReasoningCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        gradient: LinearGradient(colors: [
          const Color(0xFF4A148C).withValues(alpha: 0.4),
          const Color(0xFF6A1B9A).withValues(alpha: 0.3),
        ]),
        border: Border.all(color: const Color(0xFFCE93D8).withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Icon(
                    _expanded ? Icons.psychology : Icons.psychology_outlined,
                    color: const Color(0xFFCE93D8),
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _expanded ? 'Hide AI Reasoning' : 'See AI Reasoning',
                    style: const TextStyle(
                      color: Color(0xFFD4AF37),
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    color: const Color(0xFFCE93D8),
                    size: 20,
                  ),
                ],
              ),
            ),
          ),
          if (_expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: Text(
                widget.reasoning,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.75),
                  fontSize: 12,
                  height: 1.6,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
