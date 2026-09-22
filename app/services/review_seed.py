"""Versioned bilingual demo content, persisted by the migration; not generated AI."""
LESSON = {
    "en": {
        "title": "Newton’s Third Law", "subject": "Physics", "chapter": "Forces and Motion",
        "objective": "Understand and apply Newton’s Third Law: when one object exerts a force on a second object, the second exerts an equal and opposite force on the first.",
        "key_points": ["Forces always come in pairs: action and reaction.", "The two forces are equal in size and opposite in direction.", "They act on different objects, so they do not cancel each other.", "Both forces happen at the same time."],
        "questions": [
            {"id": "force-pairs", "kind": "choice", "text": "A car pushes a trailer forward. What force does the trailer exert on the car?",
             "options": [{"id": "equal", "text": "An equal force backward"}, {"id": "smaller", "text": "A smaller force backward"}, {"id": "none", "text": "No force on the car"}],
             "answer": "equal", "hints": ["Think about how the two objects act on each other.", "The pair has the same size, but opposite directions.", "The trailer exerts an equal force backward on the car."],
             "explanation": "The trailer exerts an equal force in the opposite direction. The forces act on different objects."},
            {"id": "different-objects", "kind": "written", "text": "Explain in your own words why action and reaction forces do not cancel.",
             "options": [], "keywords": [["different", "separate", "other"], ["object", "bodies", "body"]],
             "hints": ["Consider which object each force acts on.", "For forces to cancel, they must act on the same object.", "Action and reaction act on different objects, so they do not cancel on either object."],
             "explanation": "Action and reaction act on different objects. Cancellation requires opposing forces on the same object."}
        ],
    },
    "ar": {
        "title": "قانون نيوتن الثالث", "subject": "الفيزياء", "chapter": "القوى والحركة",
        "objective": "فهم قانون نيوتن الثالث وتطبيقه: عندما يؤثر جسم بقوة في جسم آخر، يؤثر الجسم الثاني بقوة مساوية لها في المقدار ومعاكسة لها في الاتجاه على الجسم الأول.",
        "key_points": ["تظهر القوى دائماً في أزواج: فعل ورد فعل.", "القوتان متساويتان في المقدار ومتعاكستان في الاتجاه.", "تؤثران في جسمين مختلفين، لذلك لا تلغي إحداهما الأخرى.", "تحدث القوتان في الوقت نفسه."],
        "questions": [
            {"id": "force-pairs", "kind": "choice", "text": "تدفع سيارة مقطورة إلى الأمام. ما القوة التي تؤثر بها المقطورة على السيارة؟",
             "options": [{"id": "equal", "text": "قوة مساوية إلى الخلف"}, {"id": "smaller", "text": "قوة أصغر إلى الخلف"}, {"id": "none", "text": "لا تؤثر بقوة على السيارة"}],
             "answer": "equal", "hints": ["فكر في تأثير كل جسم على الآخر.", "القوتان متساويتان في المقدار ومتعاكستان في الاتجاه.", "تؤثر المقطورة بقوة مساوية إلى الخلف على السيارة."],
             "explanation": "تؤثر المقطورة بقوة مساوية في الاتجاه المعاكس. تؤثر القوتان في جسمين مختلفين."},
            {"id": "different-objects", "kind": "written", "text": "اشرح بكلماتك لماذا لا تلغي قوتا الفعل ورد الفعل إحداهما الأخرى.",
             "options": [], "keywords": [["مختلف", "منفصل", "آخر", "اخر"], ["جسم", "أجسام", "اجسام"]],
             "hints": ["فكر في الجسم الذي تؤثر عليه كل قوة.", "لكي تتعادل القوتان، يجب أن تؤثرا في الجسم نفسه.", "تؤثر قوتا الفعل ورد الفعل في جسمين مختلفين، لذلك لا تتلاشيان على أي منهما."],
             "explanation": "تؤثر قوتا الفعل ورد الفعل في جسمين مختلفين. يتطلب التعادل قوتين متعاكستين على الجسم نفسه."}
        ],
    },
}

