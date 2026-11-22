<?php

declare(strict_types=1);

// Magic quotes no longer exist; just trim the field.
function clean_input(?string $string): string
{
    return trim($string ?? '');
}

function sanitize(?string $string): string
{
    return htmlspecialchars(trim($string ?? ''), ENT_QUOTES | ENT_HTML5, 'UTF-8');
}

function numbers_only(?string $string): int
{
    return (int) preg_replace('/[^0-9]/', '', $string ?? '');
}

// Is this a usable e-mail address?
function valid_email(string $email): bool
{
    return filter_var($email, FILTER_VALIDATE_EMAIL) !== false;
}

// "red, green ,blue" -> ['red', 'green', 'blue']
function tag_list(?string $tags): array
{
    $out = [];
    foreach (explode(',', $tags ?? '') as $value) {
        $value = trim($value);
        if ($value !== '') {
            $out[] = $value;
        }
    }
    return $out;
}
