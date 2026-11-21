#!/usr/bin/env bash
set -e

echo "正在安装开源基础叙事与前端 Skill..."
npx skills add vercel-labs/skills@find-skills
npx skills add https://github.com/danjdewhurst/story-skills --skill interactive-fiction
npx skills add inference-sh/skills@video-prompting-guide
npx skills add anthropics/skills --skill frontend-design

echo "初始化完成！请查看 AGENTS.md 与 state/task_board.json。"
