import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_provider.dart';

class WardrobeScreen extends ConsumerStatefulWidget {
  const WardrobeScreen({super.key});

  @override
  ConsumerState<WardrobeScreen> createState() => _WardrobeScreenState();
}

class _WardrobeScreenState extends ConsumerState<WardrobeScreen> {
  List<Map<String, dynamic>> _items = [];
  bool _loading = false;

  Future<void> _load() async {
    final connState = ref.read(connectionStateProvider);
    if (connState != AppConnectionState.online) return;

    final api = ref.read(apiClientProvider);
    setState(() => _loading = true);
    try {
      final raw = await api.listWardrobe();
      setState(() => _items = raw.cast<Map<String, dynamic>>());
    } catch (_) {
      // Silently fail if offline
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
        title: const Text('My Wardrobe',
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
          : _items.isEmpty
              ? _buildEmptyState()
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _items.length,
                  itemBuilder: (_, i) => _buildOutfitCard(_items[i]),
                ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 80,
            height: 80,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white.withValues(alpha: 0.06),
            ),
            child: Icon(Icons.checkroom_outlined,
                size: 40, color: Colors.white.withValues(alpha: 0.3)),
          ),
          const SizedBox(height: 16),
          Text('No saved outfits yet',
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.7), fontSize: 17)),
          const SizedBox(height: 8),
          Text(
            'Finalize an outfit in Chat to save it here',
            style: TextStyle(
                color: Colors.white.withValues(alpha: 0.4), fontSize: 13),
          ),
        ],
      ),
    );
  }

  Widget _buildOutfitCard(Map<String, dynamic> item) {
    final name = item['name'] as String? ?? 'Outfit';
    final category = item['category'] as String? ?? '';
    final metadata = item['metadata'] as Map<String, dynamic>? ?? {};
    final createdAt = item['created_at'] as String?;

    // Extract spec details
    final garment = metadata['garment_type'] as String? ?? category;
    final fabric = metadata['fabric'] as String? ?? '';
    final color = metadata['color'] as String? ?? '';
    final occasion = metadata['occasion'] as String? ?? '';

    // Tailoring info
    final tailoring = metadata['_tailoring'] as Map<String, dynamic>?;
    final hasTryon = metadata['_has_tryon'] == true;

    // Date formatting
    String dateStr = '';
    if (createdAt != null) {
      try {
        final dt = DateTime.parse(createdAt);
        dateStr =
            '${dt.day}/${dt.month}/${dt.year} ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
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
            Colors.white.withValues(alpha: 0.08),
            Colors.white.withValues(alpha: 0.03),
          ],
        ),
        border: Border.all(
            color: const Color(0xFFD4AF37).withValues(alpha: 0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header with name and badges
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                // Color dot
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: _colorFromName(color),
                    border: Border.all(
                        color: Colors.white.withValues(alpha: 0.3)),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          )),
                      if (dateStr.isNotEmpty)
                        Text(dateStr,
                            style: TextStyle(
                                color: Colors.white.withValues(alpha: 0.4),
                                fontSize: 11)),
                    ],
                  ),
                ),
                // Badges
                if (hasTryon)
                  _badge('Try-On', const Color(0xFF4A148C)),
                if (tailoring != null) ...[
                  const SizedBox(width: 6),
                  _badge('Tailored', const Color(0xFF1B5E20)),
                ],
              ],
            ),
          ),

          // Spec details
          if (garment.isNotEmpty || fabric.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  if (garment.isNotEmpty) _specChip(Icons.checkroom, garment),
                  if (fabric.isNotEmpty) _specChip(Icons.texture, fabric),
                  if (color.isNotEmpty) _specChip(Icons.palette, color),
                  if (occasion.isNotEmpty) _specChip(Icons.event, occasion),
                ],
              ),
            ),

          // Tailoring summary
          if (tailoring != null)
            _buildTailoringSummary(tailoring),

          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _buildTailoringSummary(Map<String, dynamic> tailoring) {
    final cut = tailoring['cut_measurements'] as Map<String, dynamic>?;
    final fabricReq = tailoring['fabric_requirement'] as Map<String, dynamic>?;

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          color: const Color(0xFF1B5E20).withValues(alpha: 0.15),
          border: Border.all(
              color: const Color(0xFF66BB6A).withValues(alpha: 0.2)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.straighten,
                    color: Colors.green.shade300, size: 14),
                const SizedBox(width: 6),
                Text('Tailoring',
                    style: TextStyle(
                        color: Colors.green.shade300,
                        fontSize: 12,
                        fontWeight: FontWeight.w600)),
              ],
            ),
            const SizedBox(height: 6),
            if (cut != null)
              Wrap(
                spacing: 12,
                runSpacing: 4,
                children: cut.entries
                    .where((e) => e.value != null)
                    .take(4)
                    .map((e) => Text(
                          '${e.key.replaceAll('_cut_cm', '').replaceAll('_', ' ')}: ${e.value}cm',
                          style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.7),
                              fontSize: 11,
                              fontFamily: 'monospace'),
                        ))
                    .toList(),
              ),
            if (fabricReq != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Fabric: ${fabricReq['total_meters']}m needed',
                  style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.6),
                      fontSize: 11),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _badge(String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: color.withValues(alpha: 0.3),
      ),
      child: Text(text,
          style: const TextStyle(
              color: Colors.white, fontSize: 10, fontWeight: FontWeight.w600)),
    );
  }

  Widget _specChip(IconData icon, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: Colors.white.withValues(alpha: 0.06),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: const Color(0xFFD4AF37)),
          const SizedBox(width: 4),
          Text(text,
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.7), fontSize: 11)),
        ],
      ),
    );
  }

  Color _colorFromName(String name) {
    final n = name.toLowerCase();
    if (n.contains('red') || n.contains('maroon')) return Colors.red;
    if (n.contains('blue') || n.contains('navy')) return Colors.blue;
    if (n.contains('green') || n.contains('emerald')) return Colors.green;
    if (n.contains('gold') || n.contains('yellow')) return Colors.amber;
    if (n.contains('pink') || n.contains('rose')) return Colors.pink;
    if (n.contains('purple') || n.contains('violet')) return Colors.purple;
    if (n.contains('white') || n.contains('ivory')) return Colors.white;
    if (n.contains('black')) return Colors.grey.shade800;
    if (n.contains('orange') || n.contains('coral')) return Colors.orange;
    return const Color(0xFFD4AF37);
  }
}
