<?php
// Development-only provisioning; this is deliberately outside the MCP connector.
if (!class_exists('WooCommerce')) {
    WP_CLI::error('Activate WooCommerce first.');
}
if (get_option('wc_connector_lab_seeded')) {
    $credentials = get_option('wc_connector_lab_credentials');
    if (!$credentials) {
        WP_CLI::error('Lab credentials are missing; recreate the disposable lab.');
    }
    echo '_WC_LAB_RESULT_' . json_encode($credentials) . "\n";
    return;
}
$customer_ids = [];
for ($i = 0; $i < 3; $i++) {
    $login = 'fictional-customer-' . ($i + 1);
    $user_id = username_exists($login);
    if (!$user_id) {
        $user_id = wp_create_user($login, wp_generate_password(40), $login . '@example.invalid');
    }
    if (is_wp_error($user_id)) {
        WP_CLI::error('Could not provision fictional customer.');
    }
    $customer_ids[] = (int) $user_id;
}
$product = new WC_Product_Simple();
$product->set_name('Fictional cotton T-shirt');
$product->set_regular_price('499.00');
$product->set_virtual(true);
$product->set_status('publish');
$product->save();
$statuses = ['processing', 'completed', 'pending', 'on-hold', 'failed'];
$order_ids = [];
for ($i = 0; $i < 10; $i++) {
    $order = wc_create_order(['customer_id' => $i === 9 ? 0 : $customer_ids[$i % 3]]);
    if (is_wp_error($order)) {
        WP_CLI::error('Could not create fictional order.');
    }
    $order->add_product($product, 1);
    $order->set_currency('INR');
    $order->set_date_created('2026-01-' . sprintf('%02d', $i + 1) . ' 12:00:00');
    $order->calculate_totals(false);
    $order->set_status($statuses[$i % 5]);
    $order->save();
    $order_ids[] = $order->get_id();
}
// API keys inherit user capabilities. Use a dedicated shop manager, with Read scope.
$reader_id = wp_create_user('connector-reader', wp_generate_password(40), 'reader@example.invalid');
if (is_wp_error($reader_id)) {
    $reader_id = username_exists('connector-reader');
}
if (!$reader_id) {
    WP_CLI::error('Could not provision connector reader.');
}
$reader = new WP_User($reader_id);
$reader->set_role('shop_manager');
$key = 'ck_' . bin2hex(random_bytes(20));
$secret = 'cs_' . bin2hex(random_bytes(20));
global $wpdb;
$inserted = $wpdb->insert($wpdb->prefix . 'woocommerce_api_keys', [
    'user_id' => $reader_id, 'description' => 'Fictional connector lab - Read only',
    'permissions' => 'read', 'consumer_key' => wc_api_hash($key),
    'consumer_secret' => $secret, 'truncated_key' => substr($key, -7),
]);
if (!$inserted) {
    WP_CLI::error('Could not create Read-only API key.');
}
$credentials = ['consumer_key' => $key, 'consumer_secret' => $secret,
                'customer_ids' => $customer_ids, 'order_ids' => $order_ids];
// Local disposable lab only: retain generated keys so bootstrap can be rerun.
update_option('wc_connector_lab_credentials', $credentials, false);
update_option('wc_connector_lab_seeded', true);
// bootstrap.py captures this line privately; it is never forwarded to the terminal.
echo '_WC_LAB_RESULT_' . json_encode($credentials) . "\n";
