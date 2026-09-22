import json
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

X, y = load_iris(return_X_y=True)
# BUG: undefined variable X_train (typo)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
clf = LogisticRegression(max_iter=300)
clf.fit(X_train, y_train)  # NameError on purpose
pred = clf.predict(X_test)
print(json.dumps({"accuracy": float(accuracy_score(y_test, pred))}))
