$nodePath = "C:\Users\KABUM\AppData\Local\npm-cache\_npx\8ddf6bea01b2519d\node_modules\@testsprite\testsprite-mcp\dist\index.js"
cd "E:\Sistema Mirapraia\sistema-almareia-mirapraia"

Write-Host "Running Testsprite (using existing config in testsprite_tests/tmp/config.json)..."

# Try running without arguments, hoping it picks up the config
node $nodePath generateCodeAndExecute
