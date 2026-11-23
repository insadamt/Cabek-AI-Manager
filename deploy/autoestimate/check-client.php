<?php
// Check existing credentials without changing application code or displaying secrets.
// Depends on Laravel's native bootstrap and its existing API client model.
require '/var/www/html/vendor/autoload.php';
$app = require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$token = trim(stream_get_contents(STDIN));
$valid = App\Models\ApiClient::query()->where('token_hash', hash('sha256', $token))->where('is_active', true)->exists();
echo ($valid ? 'valid' : 'invalid') . PHP_EOL;
