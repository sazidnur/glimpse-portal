# Minify player HTML for production
# Requires: npm install -g html-minifier-terser

$sourceFile = "$PSScriptRoot\..\youtube_player.html"
$outputFile = "$PSScriptRoot\..\youtube_player.min.html"

# Check if html-minifier-terser is installed
if (-not (Get-Command html-minifier-terser -ErrorAction SilentlyContinue)) {
    Write-Host "Installing html-minifier-terser..." -ForegroundColor Yellow
    npm install -g html-minifier-terser
}

Write-Host "Minifying $sourceFile..." -ForegroundColor Cyan

html-minifier-terser $sourceFile `
    --output $outputFile `
    --collapse-whitespace `
    --remove-comments `
    --remove-redundant-attributes `
    --remove-script-type-attributes `
    --remove-style-link-type-attributes `
    --minify-css true `
    --minify-js true

$originalSize = (Get-Item $sourceFile).Length
$minifiedSize = (Get-Item $outputFile).Length
$savings = [math]::Round((1 - $minifiedSize / $originalSize) * 100, 1)

Write-Host "`nDone!" -ForegroundColor Green
Write-Host "Original:  $originalSize bytes"
Write-Host "Minified:  $minifiedSize bytes"
Write-Host "Savings:   $savings%"
