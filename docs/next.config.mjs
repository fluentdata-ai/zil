import nextra from 'nextra'

const withNextra = nextra({})

export default withNextra({
  basePath: process.env.NEXT_PUBLIC_LOCAL === '1' ? undefined : '/docs',
  reactStrictMode: true,
})
