import re

s = r'https:\/\/flow-content.google\/image\/70a93c72-86ff-4e13-b788-e2088a69ae0f?Expires=1789088607\u0026KeyName=labs-flow-prod-cdn-key\u0026Signature=Q9EQobw1LRYQ8jJfk4-pY3qNXng'
raw = s.replace(r'\/', '/').replace(r'\"', '"')
print('Without unescape:', re.findall(r'https://flow-content\.google/image/[^\s"\'\\]+', raw))

raw2 = raw.replace(r'\u0026', '&').replace('&amp;', '&')
print('With unescape:', re.findall(r'https://flow-content\.google/image/[^\s"\'\\]+', raw2))
