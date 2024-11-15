from github3 import GitHub

# 不使用令牌，匿名访问
g = GitHub()

# 获取指定仓库，格式为 "所有者/仓库名"
repo = g.repository("pokemonchw","dieloli")
print(repo.__dict__)

# 获取所有发布（releases）
releases = repo.get_releases()

# 遍历并打印每个发布的信息
for release in releases:
    print("发布标题:", release.title)
    print("标签名:", release.tag_name)
    print("发布时间:", release.published_at)
    print("发布说明:", release.body)
    print("-" * 30)

