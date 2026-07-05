import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_provider.dart';

class ProductResultsScreen extends ConsumerStatefulWidget {
  const ProductResultsScreen({super.key});

  @override
  ConsumerState<ProductResultsScreen> createState() =>
      _ProductResultsScreenState();
}

class _ProductResultsScreenState extends ConsumerState<ProductResultsScreen> {
  final _queryController = TextEditingController();
  List<dynamic> _products = [];
  bool _loading = false;
  String _engine = '';

  Future<void> _search() async {
    final query = _queryController.text.trim();
    if (query.isEmpty) return;

    final connState = ref.read(connectionStateProvider);
    if (connState != AppConnectionState.online) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('⚠️ Cannot search while offline')),
        );
      }
      return;
    }

    final api = ref.read(apiClientProvider);
    setState(() => _loading = true);
    try {
      final resp = await api.searchProducts(query);
      setState(() {
        _products = resp;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Search failed: $e')),
        );
      }
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: const Text('Shop', style: TextStyle(fontWeight: FontWeight.bold)),
        centerTitle: true,
      ),
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                color: Colors.white.withValues(alpha: 0.06),
                border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _queryController,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'Search for garments...',
                        hintStyle: TextStyle(
                            color: Colors.white.withValues(alpha: 0.3)),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 14),
                      ),
                      onSubmitted: (_) => _search(),
                    ),
                  ),
                  Container(
                    margin: const EdgeInsets.only(right: 6),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      gradient: const LinearGradient(
                          colors: [Color(0xFF8B1538), Color(0xFF6A0F2B)]),
                    ),
                    child: IconButton(
                      icon: _loading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.search, color: Colors.white),
                      onPressed: _loading ? null : _search,
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Results
          Expanded(
            child: _products.isEmpty
                ? _buildEmptyState()
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: _products.length,
                    itemBuilder: (_, i) {
                      final p = _products[i] as Map<String, dynamic>;
                      return _buildProductCard(p);
                    },
                  ),
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
          Icon(Icons.shopping_bag_outlined,
              size: 56, color: Colors.white.withValues(alpha: 0.2)),
          const SizedBox(height: 12),
          Text('Search for garments above',
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.5), fontSize: 14)),
          const SizedBox(height: 4),
          Text('Real results from Myntra, AJIO, Amazon & more',
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.3), fontSize: 12)),
        ],
      ),
    );
  }

  Widget _buildProductCard(Map<String, dynamic> p) {
    final name = p['name'] as String? ?? 'Product';
    final price = p['price_inr'];
    final platform = p['platform'] as String? ?? 'Online';
    // Support both DDG format (url) and legacy format (affiliate_url)
    final url = p['url'] as String? ?? p['affiliate_url'] as String? ?? '';
    final snippet = p['snippet'] as String? ?? '';
    final isShopping = p['is_shopping_site'] == true;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(
          color: isShopping
              ? const Color(0xFFD4AF37).withValues(alpha: 0.3)
              : Colors.white.withValues(alpha: 0.08),
        ),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: url.isNotEmpty
              ? () => launchUrl(Uri.parse(url),
                  mode: LaunchMode.externalApplication)
              : null,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(
              children: [
                // Platform icon
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    color: _platformColor(platform).withValues(alpha: 0.15),
                  ),
                  child: Center(
                    child: Text(
                      platform.isNotEmpty ? platform[0].toUpperCase() : 'S',
                      style: TextStyle(
                        color: _platformColor(platform),
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                // Details
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 13,
                              fontWeight: FontWeight.w500)),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          if (price != null)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(6),
                                color: const Color(0xFF1B5E20)
                                    .withValues(alpha: 0.3),
                              ),
                              child: Text('₹${price.toString()}',
                                  style: TextStyle(
                                      color: Colors.green.shade300,
                                      fontSize: 12,
                                      fontWeight: FontWeight.w600)),
                            ),
                          if (price != null) const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(6),
                              color: Colors.white.withValues(alpha: 0.06),
                            ),
                            child: Text(platform,
                                style: TextStyle(
                                    color:
                                        Colors.white.withValues(alpha: 0.5),
                                    fontSize: 11)),
                          ),
                        ],
                      ),
                      if (snippet.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(snippet,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                color: Colors.white.withValues(alpha: 0.4),
                                fontSize: 11)),
                      ],
                    ],
                  ),
                ),
                // Arrow
                Icon(Icons.open_in_new,
                    size: 16,
                    color: Colors.white.withValues(alpha: 0.3)),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Color _platformColor(String platform) {
    final p = platform.toLowerCase();
    if (p.contains('myntra')) return Colors.pink;
    if (p.contains('ajio')) return Colors.orange;
    if (p.contains('amazon')) return Colors.amber;
    if (p.contains('flipkart')) return Colors.blue;
    if (p.contains('nykaa')) return Colors.pink.shade300;
    if (p.contains('meesho')) return Colors.deepPurple;
    return const Color(0xFFD4AF37);
  }
}
