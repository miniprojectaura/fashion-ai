import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/api_provider.dart';
import '../../core/aura_background.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen>
    with SingleTickerProviderStateMixin {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _messages = <Map<String, String>>[];
  String? _sessionId;
  final _voiceSessionId = 'voice-default';
  bool _loading = false;
  bool _recording = false;
  final _recorder = AudioRecorder();
  final _audioPlayer = AudioPlayer();
  late final AnimationController _typingCtrl;

  @override
  void initState() {
    super.initState();
    _typingCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _recorder.dispose();
    _audioPlayer.dispose();
    _typingCtrl.dispose();
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
      final resp = await api.sendChat(
        message: text,
        sessionId: _sessionId,
        language: 'te',
      );
      _sessionId = resp['session_id'] as String?;
      final reply = resp['reply'] as String;
      final products = resp['products'] as List?;
      var replyText = reply;
      if (products != null && products.isNotEmpty) {
        replyText += '\n\n🛍 ${products.length} products matched';
      }
      if (resp['outfits'] != null) {
        final variants =
            (resp['outfits']['variants'] as List?)?.length ?? 0;
        if (variants > 0) replyText += '\n👗 $variants outfit previews ready';
      }
      _addMessage('assistant', replyText);
    } catch (e) {
      _addMessage('assistant',
          '❌ Could not reach the server.\nPlease check your connection.');
    } finally {
      setState(() => _loading = false);
    }
  }

  void _addMessage(String role, String text) {
    setState(() {
      _messages.add({'role': role, 'text': text});
    });
    _scrollToBottom();
  }

  Future<void> _toggleRecording() async {
    if (_recording) {
      final path = await _recorder.stop();
      setState(() => _recording = false);

      if (path != null) {
        _addMessage('user', '🎤 Voice message sent…');
        setState(() => _loading = true);

        try {
          final api = ref.read(apiClientProvider);
          final resp = await api.voiceConverse(
            audioPath: path,
            sessionId: _voiceSessionId,
            language: 'te',
          );

          // Show transcript
          final transcript = resp['transcript'] as String? ?? '';
          if (transcript.isNotEmpty) {
            // Update the user message with actual transcript
            if (_messages.isNotEmpty && _messages.last['text'] == '🎤 Voice message sent…') {
              setState(() => _messages.last['text'] = '🎤 $transcript');
            }
          }

          // Show reply
          final replyText = resp['reply_text'] as String? ?? '';
          _addMessage('assistant', replyText);

          // Show outfit state if available
          final outfitState = resp['outfit_state'] as Map<String, dynamic>?;
          if (outfitState != null) {
            final stage = outfitState['stage'] as String? ?? '';
            if (stage == 'finalized') {
              _addMessage('assistant', '✅ Outfit finalized! Tap the button below to generate your outfit image.');
            }
          }

          // Play reply audio
          final audioUrl = resp['reply_audio_url'] as String?;
          if (audioUrl != null && audioUrl.isNotEmpty) {
            try {
              await _audioPlayer.play(UrlSource(audioUrl));
            } catch (_) {
              // Audio playback is best-effort
            }
          }
        } catch (e) {
          _addMessage('assistant', '❌ Voice processing failed: $e');
        } finally {
          setState(() => _loading = false);
        }
      }
    } else {
      if (await _recorder.hasPermission()) {
        // Record to a temp file
        final tempDir = await getTemporaryDirectory();
        final filePath = '${tempDir.path}/aura_voice_${DateTime.now().millisecondsSinceEpoch}.wav';
        await _recorder.start(
          const RecordConfig(encoder: AudioEncoder.wav),
          path: filePath,
        );
        setState(() => _recording = true);
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text(
                    'Microphone permission denied. Please enable it in Settings.')),
          );
        }
      }
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
          const SizedBox(height: 32),
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

  Widget _buildMessageBubble(Map<String, String> m) {
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
                m['text'] ?? '',
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
            // Mic button with glow when recording
            Container(
              decoration: _recording
                  ? BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: Colors.red.withValues(alpha: 0.4),
                          blurRadius: 12,
                          spreadRadius: 2,
                        ),
                      ],
                    )
                  : null,
              child: IconButton(
                icon: Icon(
                  _recording ? Icons.stop_circle : Icons.mic_outlined,
                  color: _recording
                      ? Colors.red
                      : Colors.white.withValues(alpha: 0.5),
                ),
                onPressed: _toggleRecording,
                tooltip: _recording ? 'Stop recording' : 'Voice input',
              ),
            ),
            const SizedBox(width: 4),
            Expanded(
              child: TextField(
                controller: _controller,
                style: const TextStyle(color: Colors.white, fontSize: 14.5),
                decoration: const InputDecoration(
                  hintText: 'Ask about outfits, fabrics, styling…',
                ),
                onSubmitted: (_) => _send(),
              ),
            ),
            const SizedBox(width: 8),
            // Premium send button
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
}
