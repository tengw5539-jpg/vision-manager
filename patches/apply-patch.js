#!/usr/bin/env node
/**
 * VisionPower Windows 兼容性补丁
 * ==================================
 * 问题：Windows 上 lstat() 返回的 dev 为 0，而 open()+handle.stat() 返回
 *       真实卷号，导致 isSameFileVersion() 的 dev 严格比较恒失败 ——
 *       任何图片都会报 "image_path changed during read and was rejected for safety"。
 *
 * 修复：当任一侧 dev 为 0 时视为"未知"，跳过 dev 比较；仅当两侧均为
 *       非零且不相等时判定为跨卷替换（真正需要拒绝的场景）。
 *
 * 用法：
 *   node apply-patch.js [路径...]
 *   不带参数时自动修复常见安装位置：
 *     - 全局 npm 包：<npm-global>/node_modules/visionpower/src/vision-core.js
 *     - 用户技能目录：~/.claude/skills/visionpower/describe_image.mjs
 */
const { readFileSync, writeFileSync, existsSync } = require('fs')
const { homedir } = require('os')
const { join, dirname } = require('path')
const { execSync } = require('child_process')

const OLD = `  return before.isFile()
    && after.isFile()
    && before.dev === after.dev
    && before.ino === after.ino`

const NEW = `  // Windows: lstat() reports dev=0 while handle.stat() reports the real
  // volume id, so a strict dev equality always fails there. Treat a 0 on
  // either side as "unknown" and skip the comparison; only reject when both
  // sides report a non-zero dev and they differ (a real cross-volume swap).
  const devOk = before.dev === after.dev || before.dev === 0n || after.dev === 0n
  return before.isFile()
    && after.isFile()
    && devOk
    && before.ino === after.ino`

function npmGlobalRoot() {
  try {
    return execSync('npm prefix -g', { encoding: 'utf8' }).trim()
  } catch {
    return null
  }
}

function candidatePaths() {
  const paths = []
  const npmRoot = npmGlobalRoot()
  if (npmRoot) {
    paths.push(join(npmRoot, 'node_modules', 'visionpower', 'src', 'vision-core.js'))
  }
  paths.push(join(homedir(), '.claude', 'skills', 'visionpower', 'describe_image.mjs'))
  return paths
}

function patchFile(filePath) {
  if (!existsSync(filePath)) {
    console.log(`[skip] 不存在: ${filePath}`)
    return false
  }
  const src = readFileSync(filePath, 'utf8')
  if (!src.includes('devOk')) {
    if (!src.includes(OLD)) {
      console.log(`[warn] 未找到目标代码（可能已是最新版或结构已变）: ${filePath}`)
      return false
    }
    writeFileSync(filePath, src.replace(OLD, NEW))
    console.log(`[ok]   已打补丁: ${filePath}`)
    return true
  }
  console.log(`[skip] 已打过补丁: ${filePath}`)
  return false
}

const args = process.argv.slice(2)
const targets = args.length ? args : candidatePaths()

console.log('VisionPower Windows 兼容性补丁')
console.log('='.repeat(50))
let patched = 0
for (const t of targets) {
  if (patchFile(t)) patched++
}
console.log('='.repeat(50))
console.log(patched ? `完成：${patched} 个文件已修补` : '无需修补（全部已是最新状态）')
console.log('\n提示：升级 visionpower npm 包后，重新运行本脚本即可恢复补丁。')
