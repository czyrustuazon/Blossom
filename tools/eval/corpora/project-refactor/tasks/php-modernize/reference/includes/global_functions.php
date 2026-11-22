<?php

declare(strict_types=1);

require_once __DIR__ . '/text_filter.php';
require_once __DIR__ . '/db_commands.php';
require_once __DIR__ . '/constants.php';

// A simple redirection script
function redirect_to(?string $location = null): void
{
    if ($location !== null) {
        header("Location: {$location}");
        exit;
    }
}

// Looks up a member's display name
function get_username(int $user_id): string
{
    $row = db_query('SELECT user_name FROM member_person WHERE id = ? LIMIT 1', [$user_id])->fetch();
    return $row ? $row['user_name'] : 'Guest';
}

// How many pictures a member has uploaded
function count_pictures(int $user_id): int
{
    return (int) db_query('SELECT COUNT(*) FROM pictures WHERE owner_id = ?', [$user_id])->fetchColumn();
}

function html_head(string $title): void
{
    echo '<html><head><title>' . htmlspecialchars($title, ENT_QUOTES) . '</title></head><body>';
}

function html_foot(): void
{
    echo '</body></html>';
}
