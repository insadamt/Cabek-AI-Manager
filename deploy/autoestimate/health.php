<?php
// Verify PHP-FPM and a real Laravel database connection without exposing credentials.
// Depends on the native Laravel bootstrap and PDO; hardware is unrelated to health.
require '/var/www/html/vendor/autoload.php';
$app = require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$connection = @fsockopen('127.0.0.1', 9000, $errno, $error, 2);
if ($connection === false) {
    exit(1);
}
fclose($connection);
Illuminate\Support\Facades\DB::connection()->select('SELECT 1');
