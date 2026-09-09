$ErrorActionPreference = "Continue"
$skills = @(
    "microsoft/playwright-cli@playwright-cli",
    "liarjsdev/liarjs-skills@playwright-stealth-verify",
    "currents-dev/playwright-best-practices-skill@playwright-best-practices",
    "wshobson/agents@async-python-patterns",
    "mindrally/skills@fastapi-python",
    "wshobson/agents@python-testing-patterns",
    "vercel-labs/agent-skills@vercel-react-best-practices",
    "wshobson/agents@prompt-engineering-patterns"
)

foreach ($item in $skills) {
    Write-Host "========================================="
    Write-Host "Installing: $item"
    Write-Host "========================================="
    npx skills add $item -y
}

Write-Host "All installations completed!"
