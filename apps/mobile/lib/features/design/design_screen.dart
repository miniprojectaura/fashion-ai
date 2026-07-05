

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_provider.dart';

class DesignScreen extends ConsumerStatefulWidget {
  const DesignScreen({super.key});

  @override
  ConsumerState<DesignScreen> createState() => _DesignScreenState();
}

class _DesignScreenState extends ConsumerState<DesignScreen> {
  List<Map<String, dynamic>> _designs = [];
  bool _loading = false;

  Future<void> _load() async {
    final connState = ref.read(connectionStateProvider);
    if (connState != AppConnectionState.online) return;

    final api = ref.read(apiClientProvider);
    setState(() => _loading = true);
    try {
      final raw = await api.listWardrobe();
      // Filter to items that have metadata (finalized designs)
      final designs = raw
          .cast<Map<String, dynamic>>()
          .where((item) => item['metadata'] != null)
          .toList();
      setState(() => _designs = designs);
    } catch (_) {
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: const Text('My Designs',
            style: TextStyle(fontWeight: FontWeight.bold)),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFFD4AF37)),
            onPressed: _load,
          ),
        ],
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFD4AF37)))
          : _designs.isEmpty
              ? _buildEmptyState()
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _designs.length,
                  itemBuilder: (_, i) => _buildDesignCard(_designs[i]),
                ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 90, height: 90,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(colors: [
                  const Color(0xFF8B1538).withValues(alpha: 0.3),
                  const Color(0xFF4A148C).withValues(alpha: 0.3),
                ]),
              ),
              child: const Icon(Icons.brush, size: 40, color: Color(0xFFD4AF37)),
            ),
            const SizedBox(height: 20),
            const Text('No designs yet',
                style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            Text(
              'Start a conversation in the Chat tab.\nDescribe your dream outfit, and the AI will design it for you with measurements and shopping links.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 13, height: 1.5),
            ),
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(30),
                gradient: const LinearGradient(colors: [Color(0xFF8B1538), Color(0xFF6A0F2B)]),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.auto_awesome, color: Colors.white, size: 18),
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: () {
                      // Navigate to Chat tab (index 0)
                      final shell = context.findAncestorStateOfType<State>();
                      if (shell != null && shell.mounted) {
                        // Use a simple approach — just show a hint
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('💡 Switch to the Chat tab to start designing!'),
                            backgroundColor: Color(0xFF8B1538),
                          ),
                        );
                      }
                    },
                    child: const Text('Go to Chat',
                        style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDesignCard(Map<String, dynamic> item) {
    final name = item['name'] as String? ?? 'Design';
    final meta = item['metadata'] as Map<String, dynamic>? ?? {};
    final garment = meta['garment_type'] as String? ?? '';
    final fabric = meta['fabric'] as String? ?? '';
    final color = meta['color'] as String? ?? '';
    final occasion = meta['occasion'] as String? ?? '';
    final silhouette = meta['silhouette'] as String? ?? '';
    final styleNotes = meta['style_notes'] as String? ?? '';

    final tailoring = meta['_tailoring'] as Map<String, dynamic>?;
    final createdAt = item['created_at'] as String?;

    String dateStr = '';
    if (createdAt != null) {
      try {
        final dt = DateTime.parse(createdAt);
        dateStr = '${dt.day}/${dt.month}/${dt.year}';
      } catch (_) {}
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            const Color(0xFF8B1538).withValues(alpha: 0.15),
            const Color(0xFF4A148C).withValues(alpha: 0.1),
          ],
        ),
        border: Border.all(color: const Color(0xFFD4AF37).withValues(alpha: 0.2)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Row(
              children: [
                Container(
                  width: 44, height: 44,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    gradient: const LinearGradient(colors: [Color(0xFF8B1538), Color(0xFF4A148C)]),
                  ),
                  child: const Icon(Icons.brush, color: Colors.white, size: 22),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                          style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w600)),
                      if (dateStr.isNotEmpty)
                        Text(dateStr,
                            style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 11)),
                    ],
                  ),
                ),
                if (tailoring != null)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      color: const Color(0xFF1B5E20).withValues(alpha: 0.3),
                    ),
                    child: const Text('Tailored',
                        style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w600)),
                  ),
              ],
            ),
            const SizedBox(height: 14),

            // Design details
            if (garment.isNotEmpty || fabric.isNotEmpty || color.isNotEmpty)
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  if (garment.isNotEmpty) _detailChip('👗 $garment'),
                  if (fabric.isNotEmpty) _detailChip('🧵 $fabric'),
                  if (color.isNotEmpty) _detailChip('🎨 $color'),
                  if (occasion.isNotEmpty) _detailChip('🎉 $occasion'),
                  if (silhouette.isNotEmpty) _detailChip('✂️ $silhouette'),
                ],
              ),

            // Style notes
            if (styleNotes.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(styleNotes,
                  style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.6),
                      fontSize: 12,
                      fontStyle: FontStyle.italic,
                      height: 1.4)),
            ],

            // Tailoring mini summary
            if (tailoring != null) ...[
              const SizedBox(height: 10),
              _buildMiniTailoring(tailoring),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildMiniTailoring(Map<String, dynamic> tailoring) {
    final fabricReq = tailoring['fabric_requirement'] as Map<String, dynamic>?;
    final cut = tailoring['cut_measurements'] as Map<String, dynamic>?;

    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        color: Colors.white.withValues(alpha: 0.04),
      ),
      child: Row(
        children: [
          Icon(Icons.straighten, size: 14, color: Colors.green.shade300),
          const SizedBox(width: 6),
          if (fabricReq != null)
            Text('${fabricReq['total_meters']}m fabric',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 11)),
          if (cut != null) ...[
            Text(' • ', style: TextStyle(color: Colors.white.withValues(alpha: 0.3))),
            Text('Chest: ${cut['chest_cut_cm']}cm',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 11)),
          ],
        ],
      ),
    );
  }

  Widget _detailChip(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Text(text,
          style: TextStyle(color: Colors.white.withValues(alpha: 0.75), fontSize: 12)),
    );
  }
}
