import argparse
import time

parser = argparse.ArgumentParser(description='我的命令行工具')
subparsers = parser.add_subparsers(dest='command', required=True, help='子命令')

# 子命令：push
push_parser = subparsers.add_parser('push', help='推送代码')
push_parser.add_argument('--force', action='store_true', help='强制推送')
push_parser.add_argument('remote', nargs='?', default='origin', help='远程仓库名')

# 子命令：pull
pull_parser = subparsers.add_parser('pull', help='拉取代码')
pull_parser.add_argument('--rebase', action='store_true', help='使用rebase方式')

args = parser.parse_args()

# 根据子命令执行不同逻辑
if args.command == 'push':
    print(f'推送到 {args.remote}')
    if args.force:
        print('强制推送中...')
    time.sleep(5)
    print('已推送到git仓库！')
elif args.command == 'pull':
    print('拉取代码中...')
    if args.rebase:
        print('使用 rebase 模式')